import json
from collections import Counter
from .checks import HIGH, MED, LOW, INFO

ICON = {HIGH: "🔴", MED: "🟠", LOW: "🟡", INFO: "⚪"}
LAYER = {"L1": "文件容器/时间", "L2": "文本层", "L3": "算术冗余", "L4": "流程与物理", "L5": "跨文件/表头", "L6": "统计"}


def grade(findings):
    c = Counter(f.level for f in findings)
    if c[HIGH]:
        return f"存在 {c[HIGH]} 项高风险疑点:不建议直接采信,须核对仪器内存原始数据后再定"
    if c[MED]:
        return f"存在 {c[MED]} 项中风险疑点:需要观测方解释"
    return "未发现异常(只代表本工具能查到的层面,不等于真实)"


def to_markdown(findings, files):
    L = ["# 水准原始记录真实性筛查报告", "", f"文件: {', '.join(files)}", "", f"**总评:{grade(findings)}**", ""]
    for lv in (HIGH, MED, LOW):
        sel = [f for f in findings if f.level == lv]
        if not sel:
            continue
        L.append(f"## {ICON[lv]} {lv}")
        for f in sel:
            L.append(f"- **[{f.layer} {LAYER[f.layer]}] {f.title}** ({f.file})")
            if f.detail:
                L.append(f"  - 依据:{f.detail}")
            if f.innocent:
                L.append(f"  - 可能的正常原因:{f.innocent}")
        L.append("")
    L.append("## ⚪ 通过项 / 说明")
    L += [f"- [{f.layer}] {f.title}({f.file}){(':' + f.detail) if f.detail else ''}" for f in findings if f.level == INFO]
    L += ["", "## 本工具的边界",
          "- 能证明'文件被改过'的只有**基线哈希比对**(`seal`/`verify`)。其余检查只能给出疑点,不构成定论。",
          "- 通过全部检查,不能排除:程序按公式生成并重算 Z、或改后重新导出。",
          "- 最终仲裁依据:仪器内存里的原始数据、导出日志、现场照片/GNSS 轨迹/标尺条码照等独立证据。"]
    return "\n".join(L)


def to_json(findings):
    return json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2)
