window.DEMO_DATA = {
  "generated_at": "2026-10-24",
  "note": "本数据为演示快照，非实时价格。其中 4 人方案来自真实 MCP 核价，其余为示意数据；正式版价格以麦当劳官方实时结果为准。",
  "cities": ["上海", "北京", "深圳", "广州", "杭州"],
  "datasets": [
    {
      "people": 2,
      "store": { "name": "麦当劳（静安寺店）", "address": "上海市静安区南京西路1618号" },
      "budget": 60,
      "plans": [
        {
          "tier": "经济型",
          "total": 39.0,
          "per_person": 19.5,
          "over_budget": false,
          "items": [
            { "name": "麦乐鸡4块", "qty": 2, "price": 11.5 },
            { "name": "中薯条", "qty": 1, "price": 11.0 },
            { "name": "中可乐", "qty": 2, "price": 9.0 }
          ]
        },
        {
          "tier": "均衡型",
          "total": 58.0,
          "per_person": 29.0,
          "over_budget": false,
          "items": [
            { "name": "板烧鸡腿堡", "qty": 2, "price": 23.0 },
            { "name": "中薯条", "qty": 1, "price": 11.0 },
            { "name": "麦旋风", "qty": 1, "price": 12.0 }
          ]
        },
        {
          "tier": "丰盛型",
          "total": 76.0,
          "per_person": 38.0,
          "over_budget": true,
          "items": [
            { "name": "巨无霸", "qty": 2, "price": 25.5 },
            { "name": "麦乐鸡4块", "qty": 1, "price": 11.5 },
            { "name": "大薯条", "qty": 1, "price": 13.5 },
            { "name": "中可乐", "qty": 2, "price": 9.0 }
          ]
        }
      ],
      "party": { "bookable": false, "note": "该门店暂无派对场次" }
    },
    {
      "people": 4,
      "store": { "name": "麦当劳上海黄浦华旭国际大厦餐厅", "address": "南京东路街道西藏中路336号" },
      "budget": 120,
      "real_pricing": true,
      "plans": [
        {
          "tier": "经济型",
          "total": 119.6,
          "per_person": 29.9,
          "over_budget": false,
          "items": [
            { "name": "大堡口福三件套", "qty": 4, "price": null },
            { "name": "苹果片", "qty": 4, "price": null }
          ]
        },
        {
          "tier": "均衡型",
          "total": 185.6,
          "per_person": 46.4,
          "over_budget": true,
          "items": [
            { "name": "大堡口福三件套", "qty": 4, "price": null },
            { "name": "脆脆薯条", "qty": 4, "price": null },
            { "name": "纯悦", "qty": 4, "price": null }
          ]
        },
        {
          "tier": "丰盛型",
          "total": 383.5,
          "per_person": 95.88,
          "over_budget": true,
          "items": [
            { "name": "大堡口福三件套", "qty": 4, "price": null },
            { "name": "脆脆薯条", "qty": 4, "price": null },
            { "name": "纯悦", "qty": 4, "price": null },
            { "name": "培根安格斯厚牛堡三件套", "qty": 4, "price": null },
            { "name": "“我就喜欢”鸡薯双全盒", "qty": 1, "price": null }
          ]
        }
      ],
      "party": { "bookable": false, "note": "该门店暂无派对场次" }
    },
    {
      "people": 6,
      "store": { "name": "麦当劳（五角场店）", "address": "上海市杨浦区淞沪路8号" },
      "budget": 180,
      "plans": [
        {
          "tier": "经济型",
          "total": 135.0,
          "per_person": 22.5,
          "over_budget": false,
          "items": [
            { "name": "麦乐鸡4块", "qty": 3, "price": 11.5 },
            { "name": "板烧鸡腿堡", "qty": 3, "price": 23.0 },
            { "name": "中薯条", "qty": 3, "price": 11.0 },
            { "name": "中可乐", "qty": 6, "price": 9.0 }
          ]
        },
        {
          "tier": "均衡型",
          "total": 176.0,
          "per_person": 29.33,
          "over_budget": false,
          "items": [
            { "name": "巨无霸", "qty": 3, "price": 25.5 },
            { "name": "麦辣鸡腿堡", "qty": 3, "price": 24.0 },
            { "name": "中薯条", "qty": 3, "price": 11.0 },
            { "name": "中可乐", "qty": 6, "price": 9.0 }
          ]
        },
        {
          "tier": "丰盛型",
          "total": 228.0,
          "per_person": 38.0,
          "over_budget": true,
          "items": [
            { "name": "巨无霸", "qty": 6, "price": 25.5 },
            { "name": "麦乐鸡4块", "qty": 3, "price": 11.5 },
            { "name": "大薯条", "qty": 3, "price": 13.5 },
            { "name": "麦旋风", "qty": 3, "price": 12.0 },
            { "name": "中可乐", "qty": 6, "price": 9.0 }
          ]
        }
      ],
      "party": { "bookable": true, "note": "可预约团餐位，支持企业团餐助餐" }
    }
  ]
};
