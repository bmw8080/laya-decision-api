package local.laya.sdk;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 三种问法的端到端示例：java -cp out local.laya.sdk.Demo [baseUrl]（密钥读 LAYA_API_KEY 环境变量）。 */
public class Demo {

    public static void main(String[] args) {
        String base = args.length > 0 ? args[0] : "http://127.0.0.1:8765";
        String key = System.getenv("LAYA_API_KEY");
        LayaClient c = new LayaClient(base, key);

        System.out.println("健康检查：" + c.healthz());
        System.out.println("内置问题集：" + c.presets());

        Map<String, String> teams = new LinkedHashMap<>();
        teams.put("billing", "退款/计费");
        teams.put("technical", "故障/缺陷");

        Object ticket = Map.of("body", "账单重复扣款，请退款");
        LayaClient.Decision d = c.choose(ticket, "该由哪个团队处理？", teams, 0.6);
        System.out.println("choose  → " + d);
        if (d.auto) {
            System.out.println("         自动分派给：" + d.label);
        } else {
            System.out.println("         把握不足，转人工");
        }

        LayaClient.Decision u = c.rate(Map.of("body", "系统登录失败，全组都无法使用"),
                "紧急程度", List.of("低", "中", "高"), 0.6);
        System.out.println("rate    → " + u);

        LayaClient.Decision h = c.yesNo(ticket, "需要人工介入吗？", 0.6);
        System.out.println("yes_no  → " + h);

        try {
            c.decide(Map.of("body", "x"), Map.of("bad", Map.of("type", "choice", "instructions", "i",
                    "criteria", List.of("a", "a"))), null, null);
        } catch (LayaClient.LayaException e) {
            System.out.println("错误契约 → " + e.getMessage());
        }
    }
}
