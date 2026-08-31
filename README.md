# 比特币多渠道成交量监控看板

每日自动抓取比特币在全球各交易渠道的成交量，并计算占比分布：

| 渠道 | 数据来源 | 说明 |
|---|---|---|
| 原生加密衍生品 | CoinGlass API（可选） | 未配置 Key 时按现货量 2.5 倍估算 |
| 原生加密现货 | CoinGecko 免费 API | BTC 24h 全所现货成交额 |
| CME 合规期货 | Yahoo Finance `BTC=F` | 名义额 = 合约张数 × 5 BTC × 结算价 |
| 美股现货 ETF | Yahoo Finance（IBIT/FBTC/GBTC 等 10 只） | 成交额 = 成交量 × 收盘价 |

## 文件结构

```
btc-volume-tracker/
├── fetch_data.py                    # 数据抓取脚本（仅需 requests）
├── index.html                       # 前端看板（Chart.js，环形图 + 历史趋势）
├── data.json                        # 抓取结果（自动生成/更新，保留 180 天历史）
└── .github/workflows/daily_run.yml  # 每日 UTC 21:00 自动抓取并提交
```

## 部署到 GitHub Pages（免费 + 每日自动更新）

1. 在 GitHub 新建一个 **Public** 仓库（如 `btc-volume-tracker`）
2. 把本目录全部文件推送到仓库（保留目录结构，`.github/workflows/` 必须带上）
3. 仓库 **Actions** 标签页 → 左侧 `DailyCryptoVolumeFetcher` → `Run workflow` 手动跑一次，生成初始 `data.json`
4. **Settings** → **Pages** → Build and deployment 分支选 `main`、目录 `/ (root)` → Save
5. 1-2 分钟后访问 `https://<用户名>.github.io/btc-volume-tracker/`

之后 GitHub Actions 每天自动运行，无需任何维护。

### 可选：启用 CoinGlass 真实衍生品数据

1. 到 coinglass.com 注册并获取免费 API Key
2. 仓库 **Settings → Secrets and variables → Actions** 新建 Secret：名称 `COINGLASS_API_KEY`，值为你的 Key

## 本地运行

```bash
pip install requests
python fetch_data.py   # 生成/更新 data.json
# 直接用浏览器打开 index.html，或:
python -m http.server 8000   # 访问 http://localhost:8000
```
