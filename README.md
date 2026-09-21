# OptikLink 免费服务器自动保活 & 续期脚本

> 专为 **OptikLink** 免费游戏服务器设计的自动保活与续期工具。  
> 基于 **GitHub Actions + 纯 HTTP 双轨** 架构，毫秒级执行，天然免疫网页端的流氓广告弹窗与验证码劫持。

---

## 📌 背景与官方规则

OptikLink 官方明确规定：
> **"You must login once every 3 days to our website: http://optiklink.com/auth to keep your servers online, otherwise in 7 days our system will delete your servers."**  
> （免费用户每 3 天必须登录一次网站以保持在线，连续 7 天未登录将自动删除服务器。）

由于网页端（`control.optiklink.net`）嵌入了恶意跳转广告（如 `255md.com`、`tmll7.com`）以及 reCAPTCHA 挑战，使用常规浏览器无头脚本极易受劫持或验证码阻塞。本脚本采用**纯底层 HTTP 双轨协议交互**，免受任何广告与渲染干扰。

---

## 🚀 核心架构（双轨驱动）

1. **API Key 轨（主力探活与状态监控）**：
   - 携带 Pterodactyl Client API Key 请求 `/api/client/account` 与 `/api/client`。
   - 刷新服务端账户活跃时间戳，同时拉取名下所有服务器的在线状态，并自动探测调用 `/renew` 接口。
2. **Web 网页登录轨（官方字面登录保障）**：
   - 携带会话 Cookie 访问控制台首页与账户页，模拟真实网页登录。
   - 若提供 `DISCORD_TOKEN`，在 Cookie 失效时会自动通过 Discord OAuth 授权接口换取全新 Session。
3. **Telegram 详细通知**：
   - 每次运行推送账户状态、服务器列表、执行耗时与北京时间。

---

## 🔐 GitHub Secrets 配置

在仓库设置页面（**Settings** → **Secrets and variables** → **Actions**）添加以下变量：

| Secret 名称 | 必填 | 说明 | 示例 |
|---|:---:|---|---|
| `API_KEY` | ✅ 推荐 | 面板 `Account -> API Credentials` 创建的 Client Key | `ptlc_xxxxxxxxxxxx` |
| `SERVER_ID` | ❌ 可选 | 指定服务器短 ID（留空则自动识别第一台服务器） | `a84b8e96` |
| `COOKIE` | ❌ 可选 | 网页登录 Cookie（至少含 `pterodactyl_session`） | `pterodactyl_session=...` |
| `DISCORD_TOKEN`| ❌ 可选 | Discord 账号 Token（用于 Cookie 失效时自动重登） | `OTMz...` |
| `NODE_LINK` | ❌ 可选 | 节点链接（如 `vless://`, `vmess://`, `trojan://` 等），用于出网代理 | `vless://...` |
| `PANEL_URL` | ❌ 可选 | 面板地址（默认已内嵌 `https://control.optiklink.net`） | `https://control.optiklink.net` |
| `EMAIL` | ❌ 可选 | 账号展示备注名 | `myemail@gmail.com` |
| `TG_BOT_TOKEN` | ❌ 可选 | Telegram Bot Token | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TG_CHAT_ID` | ❌ 可选 | Telegram Chat ID | `123456789` |

> 💡 **最佳实践推荐**：
> 配置 **`API_KEY`** + **`TG_BOT_TOKEN` / `TG_CHAT_ID`** 即可完美满足绝大部分保活需求；若追求绝对满足“网页登录”字面要求，建议同时配置 **`DISCORD_TOKEN`**。

---

## ⏰ 定时任务

工作流默认配置：
```yaml
schedule:
  - cron: '0 7 */2 * *'
```
- 每 2 天 UTC 7:00（北京时间 15:00）运行一次，距离 3 天限制留足 24 小时容错空间。
- 支持在 GitHub Actions 页面随时手动点击 `Run workflow` 触发。
