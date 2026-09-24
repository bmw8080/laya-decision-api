#!/usr/bin/env python3
# 生成本地决策服务（Laya）汇报用 PPTX。
# 面向领导层：只留结论、判断与对比；配置项/端口/命令等技术细节不入稿。
# 配色取自福建中烟 VI 标准色（深绿 #007355 / 金 #C8960A）。
# 用法：python tools/gen_slides.py [输出路径]
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

PRIMARY = RGBColor(0x00, 0x73, 0x55)
PRIMARY_DARK = RGBColor(0x00, 0x4D, 0x2D)
GOLD = RGBColor(0xC8, 0x96, 0x0A)
TEXT = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x6B, 0x72, 0x80)
LIGHT = RGBColor(0xF2, 0xF6, 0xF4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT = RGBColor(0xCF, 0xE3, 0xDA)
CREAM = RGBColor(0xFD, 0xF6, 0xE3)

FONT = "微软雅黑"
W, H = Inches(13.333), Inches(7.5)


def _set(run, size=16, bold=False, color=TEXT, font=FONT):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font


def slide_blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def rect(slide, x, y, w, h, fill=None):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def textbox(slide, x, y, w, h, lines, size=16, color=TEXT, bold=False,
            align=PP_ALIGN.LEFT, space_after=6, line_spacing=1.25, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if isinstance(lines, str):
        lines = [lines]
    for i, item in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        p.line_spacing = line_spacing
        if isinstance(item, tuple):
            txt = item[0]
            s = item[1] if len(item) > 1 else size
            b = item[2] if len(item) > 2 else bold
            c = item[3] if len(item) > 3 else color
        else:
            txt, s, b, c = item, size, bold, color
        r = p.add_run()
        r.text = txt
        _set(r, s, b, c)
    return tb


def title_bar(slide, title, page=None):
    rect(slide, Inches(0), Inches(0), W, Inches(1.05), fill=PRIMARY)
    rect(slide, Inches(0), Inches(1.05), W, Inches(0.045), fill=GOLD)
    textbox(slide, Inches(0.55), Inches(0.16), Inches(11.2), Inches(0.75),
            [(title, 26, True, WHITE)], anchor=MSO_ANCHOR.MIDDLE)
    if page:
        textbox(slide, Inches(12.3), Inches(6.95), Inches(0.8), Inches(0.35),
                [(str(page), 11, False, GREY)], align=PP_ALIGN.RIGHT)


def table(slide, data, x, y, w, col_w=None, row_h=Inches(0.42), head_h=Inches(0.46),
          size=12, head_size=12.5):
    rows, cols = len(data), len(data[0])
    shape = slide.shapes.add_table(rows, cols, x, y, w, head_h + row_h * (rows - 1))
    tb = shape.table
    if col_w:
        total = sum(col_w)
        for i, cw in enumerate(col_w):
            tb.columns[i].width = int(w * cw / total)
    for r, row in enumerate(data):
        tb.rows[r].height = head_h if r == 0 else row_h
        for c, val in enumerate(row):
            cell = tb.cell(r, c)
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03)
            cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRIMARY if r == 0 else (WHITE if r % 2 else LIGHT)
            tf = cell.text_frame
            tf.word_wrap = True
            run = tf.paragraphs[0].add_run()
            run.text = str(val)
            if r == 0:
                _set(run, head_size, True, WHITE)
            elif c == 0:
                _set(run, size, True, PRIMARY_DARK)
            else:
                _set(run, size, False, TEXT)
    return tb


def build(out: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 封面
    s = slide_blank(prs)
    rect(s, Inches(0), Inches(0), W, H, fill=PRIMARY_DARK)
    rect(s, Inches(0), Inches(4.28), W, Inches(0.05), fill=GOLD)
    textbox(s, Inches(1.1), Inches(2.05), Inches(11.1), Inches(1.5),
            [("本地决策服务（Laya）", 40, True, WHITE),
             ("能力、场景与推进建议", 26, False, SOFT)], space_after=14, line_spacing=1.15)
    textbox(s, Inches(1.1), Inches(3.55), Inches(11.1), Inches(0.6),
            [("把「要不要、该给谁、急不急」这类判断，交给内网里一个毫秒级的小模型", 15, False, GOLD)])
    textbox(s, Inches(1.1), Inches(6.35), Inches(11.1), Inches(0.5),
            [("2026 年 9 月", 13, False, RGBColor(0x9F, 0xC4, 0xB4))])

    # 2 一页看懂
    s = slide_blank(prs)
    title_bar(s, "一页看懂：它是什么、值不值得用", page=2)
    cards = [
        ("是什么", ["一个本地部署的判定服务：",
                 "给「情境 + 一个明确的问题」，",
                 "回「结论 + 把握程度」。",
                 "不生成文字、不解释理由。"]),
        ("解决什么", ["把离散判断（分类／分级／分派／",
                  "是非）从大模型编排里摘出来：",
                  "毫秒级返回、不花 token、",
                  "数据不出内网。"]),
        ("前提条件", ["阈值必须用我们自己的样本标定；",
                  "把握不足的判定一律交人工或大模型，",
                  "不让它替业务拍板。"]),
    ]
    x0, y0, cw, gap = Inches(0.62), Inches(1.62), Inches(3.92), Inches(0.31)
    for i, (head, body) in enumerate(cards):
        x = x0 + i * (cw + gap)
        rect(s, x, y0, cw, Inches(3.05), fill=LIGHT)
        rect(s, x, y0, cw, Inches(0.62), fill=PRIMARY)
        textbox(s, x + Inches(0.18), y0 + Inches(0.06), cw - Inches(0.36), Inches(0.5),
                [(head, 18, True, WHITE)], anchor=MSO_ANCHOR.MIDDLE)
        textbox(s, x + Inches(0.18), y0 + Inches(0.78), cw - Inches(0.36), Inches(2.1),
                [(t, 13.5, False, TEXT) for t in body], space_after=4, line_spacing=1.3)
    rect(s, Inches(0.62), Inches(5.05), Inches(12.09), Inches(1.55), fill=RGBColor(0xEC, 0xF3, 0xEE))
    textbox(s, Inches(0.85), Inches(5.2), Inches(11.6), Inches(1.3),
            [("结论：适合「高频、判断标准稳定、需要可追溯」的环节；不适合需要解释与创作的场景。",
              15.5, True, PRIMARY_DARK),
             ("它是大模型的「减负件」，不是替代品 —— 大部分简单判断在本地完成，少量不确定的才上大模型。",
              14.5, False, TEXT)], space_after=8, line_spacing=1.3)

    # 3 对比
    s = slide_blank(prs)
    title_bar(s, "为什么值得引入：本地决策服务 vs 通用大模型", page=3)
    table(s, [
        ["对比维度", "本地决策服务（本方案）", "通用大模型"],
        ["响应速度", "毫秒级（实测 8–22 毫秒）", "秒级，受网络与并发影响"],
        ["调用成本", "零 token 成本（本地算力）", "按调用量计费"],
        ["数据边界", "全本地推理，内容不出内网", "需外发或额外私有化部署"],
        ["输出形态", "标签 + 概率，口径固定可对账", "自然语言，表述每次不同"],
        ["稳定性", "同一输入结果一致，便于审计", "存在随机性"],
        ["擅长", "分类、分级、分派、是非判断", "生成、解释、长文推理"],
        ["不擅长", "解释理由、创作、开放问答", "高频重复的简单判定（贵且慢）"],
    ], Inches(0.62), Inches(1.6), Inches(12.09), col_w=[1.5, 3.4, 3.4], row_h=Inches(0.5), size=12.5)
    textbox(s, Inches(0.62), Inches(6.4), Inches(12.09), Inches(0.5),
            [("说明：实测数据取自本机部署形态（模型常驻内存约 0.7GB，可离线运行）。", 12, False, GREY)])

    # 4 实测
    s = slide_blank(prs)
    title_bar(s, "实测情况：快、稳、可离线", page=4)
    table(s, [
        ["指标", "实测结果", "对业务意味着什么"],
        ["热调用延迟", "8–22 毫秒（中位 8.45 毫秒）", "可放进提交、审批、推送等同步环节，人无感知"],
        ["首次调用", "35–58 毫秒（含模型加载 0.48 秒）", "服务常驻即可忽略；冷启动也在一秒内"],
        ["资源占用", "常驻内存约 0.7GB，无外部依赖", "单机可跑，内网离线可用"],
        ["结果稳定性", "同一输入连续 10 次结果一致", "判定口径可固定、可追溯"],
        ["把握程度分布", "标准样例 0.99；模糊样例 0.11–0.37", "阈值必须用我们自己的样本标定，不能拍"],
    ], Inches(0.62), Inches(1.62), Inches(12.09), col_w=[1.7, 4.0, 4.4], row_h=Inches(0.62), size=12.5)
    rect(s, Inches(0.62), Inches(5.35), Inches(12.09), Inches(1.25), fill=CREAM)
    textbox(s, Inches(0.85), Inches(5.5), Inches(11.6), Inches(1.0),
            [("提醒：概率经过校准，但不等于准确率；同一句话换个说法，把握程度会明显变化。", 14, False, TEXT),
             ("所以「选项怎么写、情境怎么给」本身就是要固化的业务口径。", 14, True, PRIMARY_DARK)],
            space_after=6, line_spacing=1.3)

    # 5 场景
    s = slide_blank(prs)
    title_bar(s, "可以结合的六类场景", page=5)
    table(s, [
        ["场景", "判断内容", "触发环节", "价值"],
        ["公开件自动分派", "属于哪个部门／哪一类", "提交时同步判定并写回", "减少人工派单与来回改派"],
        ["风险与紧急度分级", "低／中／高", "提交、待办生成、推送前", "高风险插队、立即通知"],
        ["是否需要人工复核", "是／否", "AI 助手回答前、审批入口", "把握不足自动兜底，不硬答"],
        ["评论与反馈分类", "投诉／咨询／建议", "反馈模块入库时", "自动打标，统计口径统一"],
        ["AI 助手输入把关", "是否越权／注入类提问", "用户输入进大模型之前", "零 token 挡风险，降低暴露面"],
        ["工具路由", "该走哪个工具／知识库", "智能体选择工具时", "多数请求不再绕大模型，降本提速"],
    ], Inches(0.62), Inches(1.58), Inches(12.09), col_w=[2.0, 2.6, 3.0, 3.2], row_h=Inches(0.62), size=12)
    textbox(s, Inches(0.62), Inches(6.45), Inches(12.09), Inches(0.5),
            [("落地时从「标准清晰、量大、判错可纠正」的场景起步，见效最快。", 12.5, True, PRIMARY_DARK)])

    # 6 三种接法
    s = slide_blank(prs)
    title_bar(s, "三种接法：不必都挂在 AI 上", page=6)
    table(s, [
        ["接法", "怎么用", "适合", "注意"],
        ["① AI 助手按需调用", "作为智能体的一个工具，由大模型决定何时调用", "需要智能判断时机、可容忍多一跳的场景", "调用链更长，适合做补充"],
        ["② 流程内直接调用", "审批提交、待办生成、推送前，由业务规则直接调用", "判定必须每次都发生、要留痕的环节", "推荐主力形态：稳定、可审计"],
        ["③ 低把握回退大模型", "本地给结论，把握不足才交给大模型或人工", "既要控成本又怕误判的场景", "阈值先行标定，避免该回的没回"],
    ], Inches(0.62), Inches(1.62), Inches(12.09), col_w=[2.2, 3.6, 3.0, 3.0], row_h=Inches(0.95), size=12)
    rect(s, Inches(0.62), Inches(5.3), Inches(12.09), Inches(1.3), fill=LIGHT)
    textbox(s, Inches(0.85), Inches(5.45), Inches(11.6), Inches(1.0),
            [("关键：三种接法共用同一套判定口径 —— 同一个问题、同一组选项；", 14, False, TEXT),
             ("换个入口不换标准，结果才对得上。这比各处各写一段提示词更可控、也更好复核。",
              14, True, PRIMARY_DARK)], space_after=6, line_spacing=1.3)

    # 7 优势/风险/举措
    s = slide_blank(prs)
    title_bar(s, "我们的优势、主要风险与应对", page=7)
    table(s, [
        ["优势", "主要风险", "应对举措"],
        ["毫秒级响应、零调用成本，可嵌入同步流程", "阈值凭感觉定，导致误判", "用脱敏历史样本标定，先跑小规模验证"],
        ["全本地推理，数据不出内网", "情境写法不规范，把握程度偏低", "先固化「情境 + 选项文案」模板，再扩场景"],
        ["判定口径固定，同输入同结果，便于审计", "被当成万能判断使用", "只用于离散判断；把握不足一律兜底"],
        ["可与现有审批与推送链路直接对接", "与既有规则重复或冲突", "先在一个场景试点，跑通再批量替换"],
    ], Inches(0.62), Inches(1.62), Inches(12.09), col_w=[4.0, 3.4, 4.6], row_h=Inches(0.78), size=12)

    # 8 落地三件事
    s = slide_blank(prs)
    title_bar(s, "落地前必须定的三件事", page=8)
    items = [
        ("一、阈值标定",
         ["拿历史单据（脱敏）跑一批，看每个场景的把握程度分布，再分档定阈值。",
          "清晰样例可达 0.99，模糊样例只有 0.11–0.37；拉不开的场景就不上。"]),
        ("二、审计留痕",
         ["每次判定可追溯到请求标识、引擎版本与耗时。",
          "事后能回答「这条为什么这么判」。"]),
        ("三、数据边界",
         ["只把必要字段送进判定，不整单外发。",
          "敏感内容优先用摘要，而非原文。"]),
    ]
    y = Inches(1.72)
    for head, body in items:
        rect(s, Inches(0.62), y, Inches(12.09), Inches(1.5), fill=LIGHT)
        rect(s, Inches(0.62), y, Inches(0.12), Inches(1.5), fill=GOLD)
        textbox(s, Inches(0.95), y + Inches(0.14), Inches(11.5), Inches(0.45),
                [(head, 17, True, PRIMARY_DARK)])
        textbox(s, Inches(0.95), y + Inches(0.62), Inches(11.5), Inches(0.8),
                [(t, 13.5, False, TEXT) for t in body], space_after=4, line_spacing=1.25)
        y += Inches(1.68)

    # 9 推进建议
    s = slide_blank(prs)
    title_bar(s, "推进建议：先验证，后扩面", page=9)
    table(s, [
        ["步骤", "做什么", "产出", "判断标准"],
        ["第一步：场景试点", "选 1–2 个高价值场景（建议：公开件分派、评论分类）", "场景对照表 + 判定口径模板", "业务方认可判得准"],
        ["第二步：数据验证", "用 100–300 条脱敏历史样本，跑准确率与把握分布", "准确率、把握分布、建议阈值", "达到可接受准确率再往下走"],
        ["第三步：小范围上线", "接入 1 个流程，把握不足回退人工，观察 2–4 周", "运行数据与问题清单", "误判可控、兜底顺畅，再扩场景"],
    ], Inches(0.62), Inches(1.62), Inches(12.09), col_w=[2.2, 4.3, 3.0, 2.8], row_h=Inches(1.0), size=12)
    textbox(s, Inches(0.62), Inches(5.8), Inches(12.09), Inches(0.9),
            [("不建议一次性铺开：先把一个场景的阈值与口径跑实，后续复用成本才是递减的。",
              14.5, True, PRIMARY_DARK)], line_spacing=1.3)

    # 10 总体评价
    s = slide_blank(prs)
    rect(s, Inches(0), Inches(0), W, H, fill=PRIMARY_DARK)
    rect(s, Inches(0), Inches(1.5), W, Inches(0.05), fill=GOLD)
    textbox(s, Inches(1.0), Inches(0.8), Inches(11.3), Inches(0.7), [("总体评价", 26, True, WHITE)])
    textbox(s, Inches(1.0), Inches(2.15), Inches(11.3), Inches(4.4), [
        ("这类本地判定服务的价值边界很清晰：高频、判断标准稳定、需要留痕的环节，它又便宜又稳；", 17, False, WHITE),
        ("需要解释、生成、长上下文推理的环节，它不适用。", 17, False, WHITE),
        ("", 8, False, WHITE),
        ("对我们当前的阶段，它是一个低成本可控的增强件：不与大模型争位置，而是把大模型的调用量、", 16.5, False, SOFT),
        ("响应时间与数据外发风险一起压下来；判定口径固定这一条，对审计与复盘尤其有价值。", 16.5, False, SOFT),
        ("", 8, False, WHITE),
        ("建议以「先验证、后扩面」的方式推进：一个场景试点跑实，再谈推广。", 17, True, GOLD),
    ], space_after=10, line_spacing=1.35)

    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "laya-汇报.pptx"
    p = build(target)
    print("已生成：" + str(p) + "  (" + str(round(p.stat().st_size / 1024)) + " KB)")
