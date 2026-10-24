# MCP 集成说明

本项目基于麦当劳中国官方 MCP（Model Context Protocol）服务开发，主交付形态为 WorkBuddy Skill，另提供一个免 Token 的静态试玩页。

## 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名 | mcd-mcp |
| 类型 | streamablehttp |
| 地址 | https://mcp.mcd.cn |
| 鉴权 | Bearer Token（环境变量 `MCD_MCP_TOKEN` 注入） |

## 使用的 Tool 及调用流程

完整调用流程（团餐方案场景）：

1. **query-nearby-stores** — 查询附近营业中门店，拿到目标门店
2. **query-meals** — 拉取门店实时菜单与套餐结构
3. **calculate-price** — 对组装好的整套方案做官方核价（换任何餐品都必须重新核价，不用菜单显示价加减）
4. （派对场景）**query-party-city** → **query-party-store** → **query-partystore-date** → **query-partystore-session** — 四级串联查询派对/团餐可预约场次

## 业务价值

把「多人聚餐」里最麻烦的三件事交给 MCP 真实数据一次算清：附近哪家门店能吃、多少人吃什么组合、总共花多少钱不超预算，并给出可对标的合计 / 人均 / 超预算结论。

## 工程约束

- 节流：滑动窗口限流，默认 300 次/分钟（官方上限 600，留一半余量）
- 重试：仅对 429 做指数退避，其余 5xx 不自动重试
- 安全：所有写操作默认 dry_run，仅显式 `--confirm` 才真实调用
- Token 仅通过环境变量注入，仓库不含任何真实凭证
