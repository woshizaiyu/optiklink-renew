#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# OptikLink 免费服务器自动保活 & 续期脚本 (纯 HTTP 极速版)
# ==============================================================================
# 背景与规则：
#   OptikLink 官方规则：FREE 用户每 3 天必须登录一次网站，否则 7 天后系统删机。
#   网页端 (control.optiklink.net) 存在恶意流氓广告跳转 (255md/tmll7) 与 reCAPTCHA 盾，
#   本脚本采用纯 HTTP 请求直接与服务端 API 及控制台交互，完全免受广告劫持与浏览器渲染卡顿影响。
#
# 双轨驱动架构：
#   1. API Key 轨 (主探活 & 状态监控)：
#      使用 Pterodactyl Client API Key (ptlc_...) 请求 /api/client/account 与 /api/client，
#      获取账户、服务器运行状态、到期/续期数据，并尝试调用 renew 接口。
#   2. Web Session / Cookie 轨 (官方字面网站登录)：
#      携带 Cookie (pterodactyl_session 等) 访问控制面板与首页，模拟用户网页登录访问；
#      若配置了 DISCORD_TOKEN，当 Cookie 失效时自动通过 Discord OAuth 完成重登与 Cookie 刷新。
#
# 环境变量 (GitHub Secrets)：
#   API_KEY        : 必填/推荐，面板 Account -> API Credentials 创建的 Client Key (ptlc_...)
#   SERVER_ID      : 可选，服务器 ID (如 a84b8e96)，留空则自动读取账户下第一台服务器
#   COOKIE         : 可选，网页端 Cookie (至少含 pterodactyl_session)
#   DISCORD_TOKEN  : 可选，Discord Token，用于 OAuth 自动化免登
#   EMAIL          : 可选，通知显示的账户标识
#   TG_BOT_TOKEN   : 可选，Telegram Bot Token
#   TG_CHAT_ID     : 可选，Telegram Chat ID
# ==============================================================================

import os
import sys
import time
import json
import urllib.parse
from datetime import datetime, timezone, timedelta

try:
    from curl_cffi import requests as http_client
    CURL_CFFI_AVAILABLE = True
except Exception:
    import requests as http_client
    CURL_CFFI_AVAILABLE = False

import requests

# ---------- 全局配置 ----------
PANEL_URL = (os.environ.get("PANEL_URL") or "https://control.optiklink.net").rstrip("/")
API_KEY = (os.environ.get("API_KEY") or "").strip()
SERVER_ID = (os.environ.get("SERVER_ID") or "").strip()
COOKIE_RAW = (os.environ.get("COOKIE") or "").strip()
DISCORD_TOKEN = (os.environ.get("DISCORD_TOKEN") or "").strip()
EMAIL = (os.environ.get("EMAIL") or "").strip()
TG_BOT_TOKEN = (os.environ.get("TG_BOT_TOKEN") or "").strip()
TG_CHAT_ID = (os.environ.get("TG_CHAT_ID") or "").strip()

# Discord OAuth 配置 (从 optiklink 页面逆向提取)
DISCORD_CLIENT_ID = "933437142254887052"
DISCORD_REDIRECT_URI = "https://optiklink.com/login"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 25


def mask(s: str, head: int = 4, tail: int = 4) -> str:
    s = s or ""
    if len(s) <= head + tail:
        return "***"
    return f"{s[:head]}...{s[-tail:]}"


def bj_time_now() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def send_telegram_message(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过消息推送")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message}
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("✅ Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {r.status_code} - {r.text[:100]}")
    except Exception as e:
        print(f"❌ Telegram 请求异常: {e}")


def format_notification(title: str, user_name: str, server_info: str, status_desc: str, details: list) -> str:
    now = bj_time_now()
    account_str = EMAIL if EMAIL else (user_name if user_name else "（未获取到）")
    lines = [
        f"🎮 {title}",
        "",
        f"📊 状态: {status_desc}",
        f"👤 账户: {account_str}",
    ]
    if server_info:
        lines.append(f"🖥️ 服务器: {server_info}")
    if details:
        lines.append("📝 详细进展:")
        for d in details:
            lines.append(f"  • {d}")
    lines.append(f"⏱️ 时间: {now} (北京时间)")
    return "\n".join(lines)


# ==============================================================================
# 模块一：Pterodactyl Client API
# ==============================================================================
def get_api_headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA
    }


def api_check_account(session) -> tuple:
    """调用 /api/client/account 验证 API 连通性并拉取用户信息"""
    url = f"{PANEL_URL}/api/client/account"
    try:
        r = session.get(url, headers=get_api_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            attrs = data.get("attributes", {})
            user = attrs.get("username") or attrs.get("email") or "User"
            email = attrs.get("email") or ""
            return True, user, email, "验证成功"
        return False, "", "", f"HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, "", "", f"请求异常: {e}"


def api_list_servers(session) -> list:
    """调用 /api/client 获取当前名下服务器列表"""
    url = f"{PANEL_URL}/api/client"
    try:
        r = session.get(url, headers=get_api_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            servers = []
            for item in data.get("data", []):
                attrs = item.get("attributes", {})
                servers.append({
                    "identifier": attrs.get("identifier"),
                    "uuid": attrs.get("uuid"),
                    "name": attrs.get("name"),
                    "node": attrs.get("node"),
                    "is_suspended": attrs.get("is_suspended", False),
                    "limits": attrs.get("limits", {})
                })
            return servers
    except Exception as e:
        print(f"⚠️ 获取服务器列表异常: {e}")
    return []


def api_try_renew(session, server_ident: str) -> tuple:
    """试探性调用续期接口 (若面板扩展了 /renew 插件)"""
    url = f"{PANEL_URL}/api/client/servers/{server_ident}/renew"
    try:
        r = session.post(url, headers=get_api_headers(), timeout=TIMEOUT)
        if r.status_code in (200, 201, 202, 204):
            return True, f"续期成功 (HTTP {r.status_code})"
        if r.status_code == 404:
            return False, "无独立 /renew 接口 (标准面板通过日常登录保活)"
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"异常: {e}"


# ==============================================================================
# 模块二：Web 页面 Session 保活与 Discord OAuth
# ==============================================================================
def parse_cookies(cookie_str: str) -> dict:
    cookies = {}
    for item in (cookie_str or "").split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def web_keepalive_visit(session, cookies: dict) -> tuple:
    """携带 Cookie 访问控制台首页，模拟真实的网页端登录活动"""
    if not cookies:
        return False, "未提供 Cookie"
    
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://optiklink.net/auth"
    }
    try:
        # 1. 访问控制台首页
        r1 = session.get(f"{PANEL_URL}/", headers=headers, cookies=cookies, timeout=TIMEOUT, allow_redirects=True)
        if "/auth" not in r1.url and "/login" not in r1.url:
            return True, f"控制台页面访问成功 ({r1.status_code})"
        
        # 2. 尝试访问 /account 路径
        r2 = session.get(f"{PANEL_URL}/account", headers=headers, cookies=cookies, timeout=TIMEOUT, allow_redirects=True)
        if "/auth" not in r2.url and "/login" not in r2.url:
            return True, f"个人中心访问成功 ({r2.status_code})"

        return False, f"重定向至登录页 (URL: {r1.url})"
    except Exception as e:
        return False, f"访问异常: {e}"


def discord_oauth_login(session) -> tuple:
    """使用 DISCORD_TOKEN 直接调取 Discord OAuth 授权接口，换取面板 Session"""
    if not DISCORD_TOKEN:
        return False, "未配置 DISCORD_TOKEN", None
    
    print("🔄 正在通过 Discord Token 执行自动化 OAuth 登录...")
    discord_headers = {
        "Authorization": DISCORD_TOKEN,
        "Content-Type": "application/json",
        "User-Agent": UA
    }
    
    payload = {
        "permissions": "0",
        "authorize": True
    }
    auth_url = (f"https://discord.com/api/v9/oauth2/authorize"
                f"?client_id={DISCORD_CLIENT_ID}"
                f"&response_type=code"
                f"&scope=guilds+guilds.join+identify+email"
                f"&redirect_uri={urllib.parse.quote(DISCORD_REDIRECT_URI)}")
    
    try:
        # 1. 向 Discord 确认授权
        resp = session.post(auth_url, headers=discord_headers, json=payload, timeout=TIMEOUT)
        if resp.status_code != 200:
            return False, f"Discord 授权失败: HTTP {resp.status_code} ({resp.text[:120]})", None
        
        location = resp.json().get("location")
        if not location:
            return False, "未获取到回调 location", None
        
        # 2. 跟随回调重定向，置换面板 Cookie
        print(f"📡 跟随回调重定向: {location[:60]}...")
        callback_resp = session.get(location, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        
        # 3. 提取 Set-Cookie
        new_cookies = {}
        for c in session.cookies:
            new_cookies[c.name] = c.value
        
        if "pterodactyl_session" in new_cookies or "session" in new_cookies:
            return True, "OAuth 自动登录成功并获得最新 Session", new_cookies
        return True, f"完成回调跳转 ({callback_resp.status_code})", new_cookies
    except Exception as e:
        return False, f"OAuth 异常: {e}", None


# ==============================================================================
# 主入口流水线
# ==============================================================================
def main():
    print("#" * 45)
    print("   OptikLink 自动保活 & 续期脚本 (纯 HTTP)")
    print("#" * 45)
    
    if not API_KEY and not COOKIE_RAW and not DISCORD_TOKEN:
        print("❌ 错误: API_KEY, COOKIE, DISCORD_TOKEN 均未配置，无法执行保活！")
        sys.exit(1)
        
    session = http_client.Session() if not CURL_CFFI_AVAILABLE else http_client.Session(impersonate="chrome124")
    details = []
    success_flags = []
    user_label = ""
    target_server_desc = ""

    # ---------- 环节 1：API 探活与信息收集 ----------
    if API_KEY:
        print(f"🔑 正在执行 API Client 探活 (Key: {mask(API_KEY, 8, 4)})...")
        ok, u_name, u_email, msg = api_check_account(session)
        if ok:
            user_label = u_name or u_email
            print(f"  ✅ API 验证通过，用户: {user_label}")
            details.append(f"API 认证有效: 用户 [{user_label}]")
            success_flags.append(True)
            
            # 拉取服务器
            servers = api_list_servers(session)
            if servers:
                print(f"  🖥️ 发现 {len(servers)} 台服务器:")
                for s in servers:
                    print(f"     • [{s['identifier']}] {s['name']} (Node: {s['node']})")
                
                # 选取目标服务器
                target = None
                if SERVER_ID:
                    for s in servers:
                        if s['identifier'] == SERVER_ID or (s['uuid'] and s['uuid'].startswith(SERVER_ID)):
                            target = s
                            break
                if not target:
                    target = servers[0]
                
                target_server_desc = f"{target['name']} ({target['identifier']})"
                details.append(f"目标服务器: {target_server_desc}")
                
                # 试探续期
                print(f"  🔄 尝试调用续期接口 [{target['identifier']}]...")
                ren_ok, ren_msg = api_try_renew(session, target['identifier'])
                print(f"     -> {ren_msg}")
                details.append(f"续期接口状态: {ren_msg}")
            else:
                print("  ℹ️ 账户下暂未查到运行中的服务器")
                details.append("服务器列表: 暂无机器")
        else:
            print(f"  ❌ API 验证未通过: {msg}")
            details.append(f"API 验证失败: {msg}")
            success_flags.append(False)
    else:
        print("ℹ️ 未配置 API_KEY，跳过 API 链路")

    # ---------- 环节 2：Web 登录保活链路 ----------
    active_cookies = parse_cookies(COOKIE_RAW)
    web_ok = False
    
    if active_cookies:
        print(f"🍪 正在测试现存 Web Cookie 登录状态...")
        web_ok, web_msg = web_keepalive_visit(session, active_cookies)
        print(f"  -> {web_msg}")
        if web_ok:
            details.append(f"Web 控制台保活成功: {web_msg}")
            success_flags.append(True)
        else:
            details.append(f"现存 Cookie 已失效: {web_msg}")
    
    # 若 Cookie 无效但配置了 Discord Token，走 OAuth 重登
    if not web_ok and DISCORD_TOKEN:
        oauth_ok, oauth_msg, new_cookies = discord_oauth_login(session)
        print(f"  -> {oauth_msg}")
        if oauth_ok:
            details.append(f"Discord 自动重登: {oauth_msg}")
            success_flags.append(True)
            # 重新访问控制台
            if new_cookies:
                w_ok, w_msg = web_keepalive_visit(session, new_cookies)
                print(f"  -> 刷新后重新访问: {w_msg}")
                details.append(f"新会话访问结果: {w_msg}")
        else:
            details.append(f"Discord 重登失败: {oauth_msg}")
            success_flags.append(False)
    elif not active_cookies and not DISCORD_TOKEN:
        print("ℹ️ 未配置 COOKIE 或 DISCORD_TOKEN，仅依赖 API 链路")

    # ---------- 环节 3：结果判定与通知 ----------
    is_overall_success = any(success_flags)
    status_title = "✅ 保活成功" if is_overall_success else "❌ 保活异常"
    status_desc = "已刷新账户登录与活跃状态" if is_overall_success else "所有保活链路均执行失败"
    
    print("\n" + "=" * 45)
    print(f"执行结果: {status_title}")
    print("=" * 45)
    
    notice_text = format_notification(
        title="OptikLink 自动保活通知",
        user_name=user_label,
        server_info=target_server_desc,
        status_desc=status_desc,
        details=details
    )
    
    send_telegram_message(notice_text)
    
    if not is_overall_success:
        sys.exit(1)
    print("🏁 执行完成，退出状态码 0")


if __name__ == "__main__":
    main()
