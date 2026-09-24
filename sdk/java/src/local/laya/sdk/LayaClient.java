package local.laya.sdk;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Laya 决策服务 Java 客户端（**零第三方依赖**，JDK 11+ 的 java.net.http 即可）。
 *
 * <pre>
 * var c = new LayaClient("http://127.0.0.1:8765", System.getenv("LAYA_API_KEY"));
 * var d = c.choose(Map.of("body", "账单重复扣款，请退款"), "该由哪个团队处理？",
 *                  Map.of("billing", "退款/计费", "technical", "故障/缺陷"), 0.6);
 * if (d.auto) { 分派(d.label); } else { 转人工(); }
 * </pre>
 */
public class LayaClient {

    public static final double TAU_DEFAULT = 0.6;

    private final String base;
    private final String apiKey;
    private final HttpClient http;
    private final Duration timeout;

    public LayaClient(String baseUrl) {
        this(baseUrl, null);
    }

    public LayaClient(String baseUrl, String apiKey) {
        this.base = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.apiKey = apiKey;
        this.timeout = Duration.ofSeconds(30);
        // 必须显式用 HTTP/1.1：JDK HttpClient 默认会先发 h2c 升级（Connection: Upgrade, HTTP2-Settings），
        // 而 uvicorn/h11 不支持明文 HTTP/2 升级，会直接回 400 "Invalid HTTP request received"。
        this.http = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    // ------------------------------------------------------------ 原始契约

    /** 原始入口：直接给 questions（{问题名: 问题定义}）或 preset，返回完整响应对象。 */
    public Map<String, Object> decide(Object state, Map<String, Object> questions, String preset,
                                     Map<String, Object> policy) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("state", state);
        if (questions != null) body.put("questions", questions);
        if (preset != null) body.put("preset", preset);
        if (policy != null && !policy.isEmpty()) body.put("policy", policy);
        return post("/v1/decide", body);
    }

    public Map<String, Object> status() {
        return get("/v1/status");
    }

    public Map<String, Object> healthz() {
        return get("/healthz");
    }

    public List<String> presets() {
        Object p = get("/v1/presets").get("presets");
        @SuppressWarnings("unchecked")
        List<String> out = p instanceof List<?> l ? (List<String>) l : List.of();
        return out;
    }

    // ------------------------------------------------------------ 语义层（三种问法）

    /** 选择类：这属于哪一类 / 该给谁。options 是「标签 → 说明」。 */
    public Decision choose(Object state, String question, Map<String, String> options, double tau) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("type", "choice");
        q.put("instructions", question);
        q.put("criteria", options);
        return toDecision(decide(state, Map.of("choice", q), null, null), "choice", tau);
    }

    /** 程度类：多严重 / 几分。levels 从低到高。 */
    public Decision rate(Object state, String question, List<String> levels, double tau) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("type", "score");
        q.put("instructions", question);
        q.put("criteria", levels);
        return toDecision(decide(state, Map.of("rating", q), null, null), "rating", tau);
    }

    /** 是非类：要不要 / 是不是。 */
    public Decision yesNo(Object state, String question, double tau) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("type", "noul");
        q.put("instructions", question);
        return toDecision(decide(state, Map.of("yes_no", q), null, null), "yes_no", tau);
    }

    // ------------------------------------------------------------ 结果对象

    public static class Decision {
        public String kind;                 // choice | score | yes_no
        public String label;                // choice：选中标签
        public String level;                // score：最接近的档位名
        public double score;                // score：期望分
        public boolean answer;              // yes_no：布尔判断
        public double probability;          // yes_no：P(是)
        public double confidence;           // 把握程度
        public boolean auto;                // confidence >= tau → 可自动处理
        public boolean needsReview;         // 反之：建议人工/大模型复核
        public Map<String, Object> distribution = Map.of();
        public Map<String, Object> usage = Map.of();
        public Map<String, Object> raw = Map.of();

        @Override
        public String toString() {
            return switch (kind) {
                case "choice" -> "choice=" + label + " conf=" + round(confidence) + " auto=" + auto + " dist=" + distribution;
                case "score" -> "score=" + round(score) + " level=" + level + " conf=" + round(confidence) + " auto=" + auto;
                default -> "yes_no=" + answer + " P(true)=" + probability + " conf=" + round(confidence) + " auto=" + auto;
            };
        }

        private static double round(double v) { return Math.round(v * 10000.0) / 10000.0; }
    }

    public static class LayaException extends RuntimeException {
        public final String code;
        public final int status;

        public LayaException(String code, String message, int status) {
            super(code + " (" + status + "): " + message);
            this.code = code;
            this.status = status;
        }
    }

    // ------------------------------------------------------------ 内部

    @SuppressWarnings("unchecked")
    private Decision toDecision(Map<String, Object> resp, String qid, double tau) {
        Decision d = new Decision();
        Map<String, Object> answers = (Map<String, Object>) resp.getOrDefault("answers", Map.of());
        Map<String, Object> a = (Map<String, Object>) answers.getOrDefault(qid, Map.of());
        d.raw = resp;
        d.usage = (Map<String, Object>) resp.getOrDefault("usage", Map.of());
        double conf = num(a.get("confidence"));
        d.confidence = conf;
        d.auto = conf >= tau;
        d.needsReview = !d.auto;
        String type = String.valueOf(a.getOrDefault("type", ""));
        if ("choice".equals(type)) {
            d.kind = "choice";
            d.label = String.valueOf(a.get("choice"));
            d.distribution = (Map<String, Object>) a.getOrDefault("probabilities", Map.of());
        } else if ("score".equals(type)) {
            d.kind = "score";
            d.score = num(a.get("score"));
            d.distribution = (Map<String, Object>) a.getOrDefault("probabilities", Map.of());
            Map<String, Object> legend = (Map<String, Object>) a.getOrDefault("legend", Map.of());
            Object name = legend.get(String.valueOf((int) Math.round(d.score)));
            d.level = name != null ? String.valueOf(name) : null;
        } else {
            d.kind = "yes_no";
            d.probability = num(a.get("noul"));
            d.answer = d.probability >= 0.5;
        }
        return d;
    }

    private static double num(Object o) {
        return o instanceof Number n ? n.doubleValue() : 0.0;
    }

    private Map<String, Object> post(String path, Object payload) {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(base + path))
                .timeout(timeout)
                .header("content-type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(Json.write(payload)));
        return send(b);
    }

    private Map<String, Object> get(String path) {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(base + path)).timeout(timeout).GET();
        return send(b);
    }

    private Map<String, Object> send(HttpRequest.Builder b) {
        if (apiKey != null && !apiKey.isBlank()) b.header("X-API-Key", apiKey);
        HttpResponse<String> r;
        try {
            r = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
        } catch (Exception e) {
            throw new LayaException("TRANSPORT", e.getMessage(), 0);
        }
        Map<String, Object> body = Json.parseObject(r.body());
        if (r.statusCode() >= 400) {
            @SuppressWarnings("unchecked")
            Map<String, Object> err = (Map<String, Object>) body.getOrDefault("error", Map.of());
            throw new LayaException(String.valueOf(err.getOrDefault("code", "INTERNAL")),
                    String.valueOf(err.getOrDefault("message", r.body())), r.statusCode());
        }
        return body;
    }
}
