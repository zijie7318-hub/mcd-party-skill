# 派对四级查询详解（City → Store → Date → Session）

> 供 SKILL.md Step 5 使用。原则：只查可预约信息，绝不真实下单（写操作默认 dry_run）。

## 前置：拿 spuId

先调 `mall-points-products`（`catRuleIds="1>6>20,1>6>21"`）→ 从返回里选一个派对商品的 `spuId`（默认选生日类/主题类常规款，按 `status=2` 上架中筛选）。

## 四级链路

| 级 | 工具 | 关键入参 | 关键出参 |
|---|---|---|---|
| 1 城市 | `query-party-city` | `spuId` | 城市 `code`、`latitude`、`longitude` |
| 2 门店 | `query-party-store` | `code`、`latitude`、`longitude`、`spuId` | 门店 `code`（字段名是 code，不是 storeCode） |
| 3 日期 | `query-party-store-date` | `storeCode`=上一步 code、`spuId` | 可预约日期，字段名 `date` |
| 4 场次 | `query-party-store-session` | `storeCode`、`dateStr`=上一步 date、`spuId` | 场次时间、`partyMin`/`partyMax` 成团人数、`leftNum` 剩余、`price` |

## 坑点（真机实测）

- 门店编码字段名是 `code`，不是 storeCode——容易看错
- 日期返回字段名 `date`，传给 session 时入参名是 `dateStr`
- 场次 `price` 单位是"分"，÷100 转元
- `query-party-store-date` 返回空数组（`data:[]`）或报错 → **立即短路 `party.bookable=false`**，note 说明"该门店暂无派对场次"，不再继续调 session（没有日期就必然没有场次）
- `query-party-store` 查不到所选门店 / 城市无派对 → 同样 bookable=false 并说明，不编造场次

## 实测参考（2026-10-25）

- 上海 store 1450713：spuId=8084，可约 10-28 ~ 11-03，每场 50 元 / 5-12 人
- 西安京东 MALL 曲江店（store 1960632）：无派对场次；附近万科翡翠国际约 960m、曲江龙湖约 1.35km 可办
