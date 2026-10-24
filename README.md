# 麦门聚餐管家 · mcd-party-skill

> 多人麦当劳聚餐，选店、按预算出三套方案、官方核价、派对预约，一键理清怎么点。

**在线试玩**：https://zijie7318-hub.github.io/mcd-party-skill/

麦当劳程序员创意开发大赛参赛作品（基于麦当劳官方 MCP 开发的 WorkBuddy Skill）。本作品同时参与 WaytoAGI 1024 切磋大会「用餐」赛道。

---

## 它能干什么

- **团餐方案生成**：输入城市 + 人数 + 预算，自动查附近营业中门店、拉真实菜单，按「经济型 / 均衡型 / 丰盛型」组装至少 2 套方案，输出合计、人均、是否超预算
- **派对 / 团餐预约**：串联 城市 → 门店 → 日期 → 场次 四级查询，输出可预约信息（默认不真实下单）
- **免 Token 在线试玩**：打开即玩，无需申请 MCP Token，无需安装任何东西

---

## 安装方法

### 1. 申请 MCP Token

访问 [open.mcd.cn/mcp](https://open.mcd.cn/mcp)，用手机号登录 → 右上角「控制台」→「激活」→ 复制 Token。

### 2. 在 WorkBuddy 中配置

在连接器里配置 `mcd-mcp`：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

### 3. 加载 Skill

将本仓库的 `SKILL.md` 作为 WorkBuddy Skill 加载，或直接在工作区对话中触发。

---

## 使用示例

> 用户：帮我安排 4 个人的聚餐，预算 120 块，在徐家汇附近。

助手会依次：查附近门店 → 拉实时菜单 → 组装三套方案 → 官方核价 → 输出：

| 方案 | 合计 | 人均 | 是否超预算 |
|---|---|---|---|
| 经济型 | ¥89.0 | ¥22.25 | 预算内 |
| 均衡型 | ¥118.5 | ¥29.63 | 预算内 |
| 丰盛型 | ¥156.0 | ¥39.0 | 超出预算 |

---

## 目录结构

```
mcd-party-skill/
├─ SKILL.md                    # WorkBuddy 技能定义
├─ scripts/
│  ├─ party_chain.py           # MCP 链路编排
│  ├─ party_planner.py         # 方案组装 + 核价
│  └─ demo_data.py             # 演示数据生成
├─ docs/
│  ├─ index.html               # 免 Token 试玩页
│  └─ data.js                  # 演示数据快照
├─ README.md
├─ CONTEST_DECLARATION.md      # 参赛声明（官方原文）
├─ MCP_INTEGRATION.md          # MCP 使用说明
├─ mcp-config.example.json     # 配置示例（占位符）
└─ .gitignore
```

---

## 目标用户

需要组织多人麦当劳聚餐的人——团建、宿舍聚会、生日派对、临时拼单，不想自己一家家凑菜单、算人均、比预算。

---

## 合规声明

- 本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品
- 餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准
- 本工具不代下单、不碰支付，写操作默认 dry_run
- 仓库内不含任何真实 Token、密钥或个人信息，配置仅使用环境变量占位符

---

喜欢的话，点个 Star ⭐ 支持一下！有问题欢迎提 [Issue](https://github.com/zijie7318-hub/mcd-party-skill/issues)。
