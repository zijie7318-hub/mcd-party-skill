# 工具实测坑点与优惠工具边界

> 搭方案/核价遇疑难时查此文件。全部来自真机实测（2026-10-25，上海/西安两轮）。

## 菜单与时段

- **时段菜单**：`query-meals` 返回的可能是早餐菜单（约 05:14–10:15，各店略有差异）或正餐菜单。**以 query-meals 实际返回为准**——预约时段文案写的切换时间可能偏早（实测有门店文案写 10:15 截止、10:21 仍返回早餐菜单）
- 早餐时段没有"多人餐/小食拼盘"分类 → 用「双人餐 + 单品堡/小食/冰淇淋」组合替代，输出注明"当前为早餐时段菜单"并主动提出可切换；用户要求正餐时，重新调 query-meals 确认菜单已切换再搭方案

## 价格单位

- `query-meals` 菜单显示价为"元"；`calculate-price` 与派对场次返回价格为"分"，÷100 转"元"

## 随单购卡价陷阱

- 菜单中 `discountType` 为"随单购早餐卡优惠"/"随单购麦金卡优惠"且 `canWithOrder=true` 的餐品，`currentPrice` 必须随单购买对应卡（`withOrder.cardId`）才能享受；核价不传 `withOrder` 会按 `originalPrice` 计
- 默认优先选 `discountType=null` 的餐品；若卡惠餐品更划算，把 query-meals 返回的 `withOrder`（cardId/cardType）带进 calculate-price，连同卡价一起核总价后对比取舍

## 核价返回

- 餐品名以 `calculate-price` 返回的 `productName` 为准（可能与 query-meals 菜单名略有差异，如"美式"→"冰美式中杯"）

## 优惠工具边界

- `query-store-coupons`：门店+订单类型可用券（couponId/couponCode/tradeDateTime/products）
- `query-my-coupons`：用户卡包里的券及用券价格
- `available-coupons`：可领未领的券——只提示用户去领，**不代领**（领券是写操作）
- `campaign-calendar`：当月活动日历，只作搭配参考，真实优惠以 calculate-price 为准
- `query-promotions`：**仅团餐场景**（beType=6）；到店满减/第二份半价等由 calculate-price 自动计算，看返回的 `discount`/`enjoyed`/`balance`

## 实测数据参考

- 上海 store 1450713：三档核价 89.90 / 118.80 / 160.60
- 西安 store 1960632（金地广场餐厅）：三档核价 69.90 / 100.40 / 136.40
- 叠券实测：新人专享-中杯美式7折券（couponId `365A627ABDC435D840984F03055DF097` / couponCode `MCD610YE070002T90068A`）使美式中杯 19→13.3，叠券三档 78.20 / 94.70 / 149.70，每档省 5.70
