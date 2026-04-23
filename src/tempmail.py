#!/usr/bin/env python3
import asyncore
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import signal
import smtplib
import smtpd
import sqlite3
import string
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

DB_PATH = os.environ.get("TEMPMAIL_DB", "/var/lib/tempmail/messages.db")
DOMAIN = os.environ.get("TEMPMAIL_DOMAIN", "emali.net").strip().lower()
HTTP_HOST = os.environ.get("TEMPMAIL_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("TEMPMAIL_HTTP_PORT", "80"))
SMTP_HOST = os.environ.get("TEMPMAIL_SMTP_HOST", "0.0.0.0")
SMTP_PORT = int(os.environ.get("TEMPMAIL_SMTP_PORT", "25"))
TTL_HOURS = int(os.environ.get("TEMPMAIL_TTL_HOURS", "24"))
MAX_MESSAGE_BYTES = int(os.environ.get("TEMPMAIL_MAX_MESSAGE_BYTES", str(10 * 1024 * 1024)))
MAX_TEXT_CHARS = 200000
DAILY_SEND_LIMIT = int(os.environ.get("TEMPMAIL_DAILY_SEND_LIMIT", "5"))
MAILBOX_DAILY_LIMIT = int(os.environ.get("TEMPMAIL_MAILBOX_DAILY_LIMIT", "0"))
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 3 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTS = {".jpg", ".jpeg", ".png", ".pdf", ".webp", ".gif", ".txt"}
ALLOWED_REGISTRATION_DOMAINS = {"gmail.com", "qq.com", "163.com"}
CODE_TTL_MINUTES = 10
CODE_RESEND_SECONDS = 60
UTC8 = timezone(timedelta(hours=8))
PASSWORD_ITERATIONS = 180000
SESSION_DAYS = 14
ADMIN_USERNAME = (os.environ.get("TEMPMAIL_ADMIN_USERNAME") or "admin").strip() or "admin"
ADMIN_EMAIL = (os.environ.get("TEMPMAIL_ADMIN_EMAIL") or f"{ADMIN_USERNAME}@{DOMAIN}").strip() or f"{ADMIN_USERNAME}@{DOMAIN}"
ADMIN_PASSWORD = os.environ.get("TEMPMAIL_ADMIN_PASSWORD", "")
ADMIN_SALT = os.environ.get("TEMPMAIL_ADMIN_SALT", "")
ADMIN_PASSWORD_HASH = os.environ.get("TEMPMAIL_ADMIN_PASSWORD_HASH", "")
BOX_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
DB_LOCK = threading.Lock()
LANG_CODES = ["en", "ru", "ar", "es", "zh-CN", "zh-TW", "de", "it", "fr", "pt", "ja", "ko"]
SEO_KEYWORDS = ", ".join([
    "temporary email", "temp mail", "disposable email", "free inbox", "anonymous email",
    "временная почта", "одноразовая почта", "بريد مؤقت", "correo temporal", "correo desechable",
    "临时邮箱", "临时邮件", "臨時信箱", "一次性信箱", "temporäre email", "wegwerf email",
    "email temporanea", "email temporária", "メール 一時", "임시 이메일"
])

HTML_PAGE = r"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>临时邮箱 - Temp Mail Inbox</title>
<meta name="description" content="Create a temporary email inbox, receive messages for 24 hours, and send email after login.">
<meta name="keywords" content="__SEO_KEYWORDS__">
<meta name="robots" content="index,follow">
<link rel="canonical" href="https://__DOMAIN__/">
<link rel="alternate" hreflang="en" href="https://__DOMAIN__/?lang=en">
<link rel="alternate" hreflang="ru" href="https://__DOMAIN__/?lang=ru">
<link rel="alternate" hreflang="ar" href="https://__DOMAIN__/?lang=ar">
<link rel="alternate" hreflang="es" href="https://__DOMAIN__/?lang=es">
<link rel="alternate" hreflang="zh-CN" href="https://__DOMAIN__/?lang=zh-CN">
<link rel="alternate" hreflang="zh-TW" href="https://__DOMAIN__/?lang=zh-TW">
<link rel="alternate" hreflang="de" href="https://__DOMAIN__/?lang=de">
<link rel="alternate" hreflang="it" href="https://__DOMAIN__/?lang=it">
<link rel="alternate" hreflang="fr" href="https://__DOMAIN__/?lang=fr">
<link rel="alternate" hreflang="pt" href="https://__DOMAIN__/?lang=pt">
<link rel="alternate" hreflang="ja" href="https://__DOMAIN__/?lang=ja">
<link rel="alternate" hreflang="ko" href="https://__DOMAIN__/?lang=ko">
<link rel="alternate" hreflang="x-default" href="https://__DOMAIN__/">
<meta property="og:title" content="临时邮箱 - Temp Mail Inbox">
<meta property="og:description" content="Create a temporary email inbox, receive messages for 24 hours, and send email after login.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://__DOMAIN__/">
<style>
:root{color-scheme:light;--ink:#151515;--muted:#5f6368;--line:#d7dce2;--bg:#f4f6f8;--surface:#fff;--soft:#e9f6f1;--danger:#c92a2a}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}header{border-bottom:1px solid var(--line);background:#fff}.wrap{width:min(1180px,calc(100% - 32px));margin:0 auto}.top{min-height:80px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px}h1{font-size:30px;line-height:1.1;margin:0 0 6px}.tag{margin:0;color:var(--muted);font-size:14px}.tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}select,input,textarea{border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);font:inherit}select{min-height:40px;padding:0 10px}.pill{color:var(--muted);font-size:14px}main{padding:22px 0 36px}.tabs{display:flex;gap:8px;margin:0 0 16px;flex-wrap:wrap}.tab{min-height:42px;border:1px solid var(--line);border-radius:8px;padding:0 14px;background:#fff;color:var(--ink);cursor:pointer;font-weight:700}.tab.active{background:var(--ink);color:#fff;border-color:var(--ink)}.bar{display:grid;grid-template-columns:1fr auto auto auto;gap:10px;align-items:center;margin-bottom:18px}.addr{width:100%;min-height:46px;padding:0 12px;font-size:18px}button{min-height:44px;border:1px solid var(--ink);border-radius:8px;padding:0 15px;background:var(--ink);color:#fff;cursor:pointer;font-weight:700}button.secondary{background:#fff;color:var(--ink)}button.danger{background:#fff;color:var(--danger);border-color:var(--danger)}button:disabled{opacity:.55;cursor:not-allowed}.view{display:none}.view.active{display:block}.grid{display:grid;grid-template-columns:380px 1fr;gap:18px;align-items:start}.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}.head{min-height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--line);font-weight:700;gap:12px}.body{padding:18px}.list{min-height:480px;max-height:65vh;overflow:auto}.empty{padding:22px;color:var(--muted);line-height:1.5}.msg{width:100%;display:block;padding:12px 14px;border:0;border-bottom:1px solid var(--line);background:#fff;color:var(--ink);text-align:start;cursor:pointer;border-radius:0;min-height:76px}.msg:hover,.msg.active{background:var(--soft)}.ms{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mm{margin-top:6px;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.reader{min-height:480px;max-height:65vh;overflow:auto;padding:18px}.reader h2{margin:0 0 8px;font-size:22px;line-height:1.25;word-break:break-word}.meta{color:var(--muted);font-size:14px;line-height:1.5;margin-bottom:16px;word-break:break-word}pre{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;font-family:Consolas,Menlo,monospace;font-size:14px;line-height:1.5;margin:0}.notice{margin-top:12px;color:var(--muted);font-size:13px;line-height:1.45}.form{display:grid;gap:12px;max-width:760px}.form label{display:grid;gap:6px;font-weight:700}.form input,.form textarea{width:100%;min-height:44px;padding:10px 12px}.form textarea{min-height:180px;resize:vertical;line-height:1.45}.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}.result{margin-top:12px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--muted);line-height:1.45}.result.ok{border-color:#8ce0bd;color:#087f5b}.result.err{border-color:#f0a0a0;color:var(--danger)}.kv{display:grid;grid-template-columns:140px 1fr;gap:8px;margin:0 0 14px;color:var(--muted)}.kv strong{color:var(--ink)}table{width:100%;border-collapse:collapse;background:#fff}th,td{border-bottom:1px solid var(--line);padding:10px;text-align:start;font-size:14px;word-break:break-word}th{color:var(--muted);font-weight:700}[dir=rtl] .tools{justify-content:flex-start}@media(max-width:860px){.top{grid-template-columns:1fr;padding:16px 0}.tools{justify-content:flex-start}.bar{grid-template-columns:1fr 1fr}.addr{grid-column:1/-1;font-size:16px}.grid,.two{grid-template-columns:1fr}.list,.reader{max-height:none;min-height:260px}.kv{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><div class="wrap top"><div><h1 data-k="brand">临时邮箱</h1><p class="tag" data-k="tag">Temporary inbox with private sign-in and limited sending.</p></div><div class="tools"><span class="pill" id="pill"></span><select id="lang" aria-label="Language"></select></div></div></header>
<main class="wrap">
<nav class="tabs"><button class="tab active" data-tab="inbox" data-k="inbox">收件箱</button><button class="tab" data-tab="send" data-k="send">发送</button><button class="tab" data-tab="account" data-k="account">Account</button><button class="tab" data-tab="admin" id="adminTab" data-k="admin">Admin</button></nav>
<section class="bar"><input class="addr" id="address" autocomplete="off" spellcheck="false"><button id="copy" data-k="copy">复制</button><button class="secondary" id="newbox" data-k="newBox">New</button><button class="secondary" id="refresh" data-k="refresh">刷新</button></section>
<section id="view-inbox" class="view active"><div class="grid"><div class="panel"><div class="head"><span data-k="inbox">收件箱</span><button class="danger" id="clear" data-k="clear">Clear</button></div><div class="list" id="list"><div class="empty" data-k="noMail">还没收到邮件。</div></div></div><div class="panel"><div class="head"><span data-k="message">Message</span><button class="danger" id="delete" disabled data-k="delete">Delete</button></div><div class="reader" id="reader"><div class="empty" data-k="choose">Choose a message.</div></div></div></div><div class="notice" data-k="notice">Messages expire automatically after 24 hours. Anyone who knows the mailbox name can read it.</div></section>
<section id="view-send" class="view"><div class="panel"><div class="head"><span data-k="sendTitle">发送 Email</span><span id="quota"></span></div><div class="body"><div class="kv"><strong data-k="from">From</strong><span id="fromAddr">-</span></div><form id="sendForm" class="form"><label><span data-k="to">To</span><input id="sendTo" autocomplete="email" data-ph="phTo"></label><label><span data-k="subject">主题</span><input id="send主题" maxlength="200" data-ph="ph主题"></label><label><span data-k="body">正文</span><textarea id="send正文" maxlength="20000" data-ph="ph正文"></textarea></label><button id="sendButton" type="submit" data-k="send">发送</button></form><div id="sendResult" class="result"></div></div></div></section>
<section id="view-account" class="view"><div class="two"><div class="panel"><div class="head"><span data-k="login">登录</span></div><div class="body"><form id="loginForm" class="form"><label><span data-k="loginId">用户名或邮箱</span><input id="loginId" autocomplete="username"></label><label><span data-k="password">密码</span><input id="login密码" type="password"></label><button type="submit" data-k="login">登录</button></form></div></div><div class="panel"><div class="head"><span data-k="register">Register</span></div><div class="body"><form id="registerForm" class="form"><label><span data-k="username">Username</span><input id="regUsername"></label><label><span data-k="email">Email</span><input id="regEmail" autocomplete="email"></label><button type="button" class="secondary" id="requestCode" data-k="sendCode">发送 code</button><label><span data-k="code">Code</span><input id="regCode" inputmode="numeric" autocomplete="one-time-code"></label><label><span data-k="password">密码</span><input id="reg密码" type="password"></label><button type="submit" data-k="register">Register</button></form></div></div></div><div class="panel" style="margin-top:18px"><div class="head"><span data-k="account">Account</span><button class="secondary" id="logout" data-k="logout">退出</button></div><div class="body"><div id="accountResult" class="result"></div></div></div></section>
<section id="view-admin" class="view"><div class="panel"><div class="head"><span data-k="adminTitle">Admin System</span><button class="secondary" id="reloadUsers" data-k="refresh">刷新</button></div><div class="body"><div id="adminResult" class="result"></div><h2 data-k="users">Users</h2><div style="overflow:auto"><table><thead><tr><th data-k="username">Username</th><th data-k="email">Email</th><th data-k="role">Role</th><th data-k="created">Created</th><th data-k="today">发送成功 today</th><th data-k="total">发送成功 total</th></tr></thead><tbody id="users正文"></tbody></table></div><h2 data-k="currentMail">Current mail</h2><div style="overflow:auto"><table><thead><tr><th>ID</th><th data-k="inbox">收件箱</th><th data-k="from">From</th><th data-k="subject">主题</th><th data-k="body">正文</th><th data-k="created">Created</th></tr></thead><tbody id="mail正文"></tbody></table></div><h2 data-k="archives">Archives</h2><div style="overflow:auto"><table><thead><tr><th>ID</th><th data-k="inbox">收件箱</th><th data-k="from">From</th><th data-k="subject">主题</th><th data-k="body">正文</th><th data-k="created">Created</th></tr></thead><tbody id="archive正文"></tbody></table></div></div></div></section>
<noscript><p>Temporary email, disposable inbox, receive mail, send mail, временная почта, بريد مؤقت, correo temporal, 临时邮箱, 臨時信箱, temporäre email, email temporanea.</p></noscript>
</main><script>
const domain="__DOMAIN__";
const languages=[["en","English"],["ru","Русский"],["ar","العربية"],["es","Español"],["zh-CN","简体中文"],["zh-TW","繁體中文"],["de","Deutsch"],["it","Italiano"],["fr","Français"],["pt","Português"],["ja","日本語"],["ko","한국어"]];
const D={
 en:{brand:"Temp Mail",tag:"Temporary inbox with private sign-in and limited sending.",inbox:"Inbox",send:"发送",account:"Account",admin:"Admin",copy:"Copy",newBox:"New",refresh:"Refresh",clear:"Clear",message:"Message",delete:"Delete",noMail:"还没收到邮件。",choose:"Choose a message.",notice:"Messages expire automatically after 24 hours. Anyone who knows the mailbox name can read it.",sendTitle:"发送 Email",from:"From",to:"To",subject:"主题",body:"正文",login:"登录",register:"Register",logout:"退出",username:"Username",email:"Email",password:"密码",loginId:"用户名或邮箱",adminTitle:"Admin System",role:"Role",created:"Created",today:"发送成功 today",total:"发送成功 total",phTo:"recipient@example.com",ph主题:"Message subject",ph正文:"Write your message",signedOut:"Not signed in",signedIn:"Signed in as {user}",quotaGuest:"Guest quota: {used}/{limit} today",quotaAdmin:"Admin: no daily send limit",must登录:"登录 is required to send mail.",sent:"Sent.",sendFail:"发送 failed: {error}",loading:"Loading...",loginOk:"登录成功.",logoutOk:"Logged out.",createdOk:"Account created.",adminOnly:"Admin access required.",code:"Verification code",sendCode:"发送 code",codeSent:"Verification code sent.",attachments:"Attachments",users:"Users",currentMail:"Current mail",archives:"Archives",seoTitle:"临时邮箱 - Temp Mail Inbox",seoDescription:"Create a temporary email inbox, receive messages for 24 hours, and send email after login."},
 ru:{brand:"Временная почта",tag:"Временный ящик, вход в аккаунт и ограниченная отправка.",inbox:"Входящие",send:"Отправить",account:"Аккаунт",admin:"Админ",copy:"Копировать",newBox:"Новый",refresh:"Обновить",clear:"Очистить",message:"Письмо",delete:"Удалить",noMail:"Писем пока нет.",choose:"Выберите письмо.",notice:"Письма удаляются через 24 часа. Кто знает имя ящика, может читать его.",sendTitle:"Отправить email",from:"От",to:"Кому",subject:"Тема",body:"Текст",login:"Вход",register:"Регистрация",logout:"Выйти",username:"Имя",email:"Email",password:"Пароль",loginId:"Имя или email",adminTitle:"Панель администратора",role:"Роль",created:"Создан",today:"Сегодня",total:"Всего",phTo:"recipient@example.com",ph主题:"Тема письма",ph正文:"Введите текст",signedOut:"Вход не выполнен",signedIn:"Вход: {user}",quotaGuest:"Лимит: {used}/{limit} сегодня",quotaAdmin:"Админ: без дневного лимита",must登录:"Для отправки нужен вход.",sent:"Отправлено.",sendFail:"Ошибка отправки: {error}",loading:"Загрузка...",loginOk:"Вы вошли.",logoutOk:"Вы вышли.",createdOk:"Аккаунт создан.",adminOnly:"Нужен админ-доступ.",seoTitle:"Временная почта - одноразовый email",seoDescription:"Создайте временный почтовый ящик, получайте письма 24 часа и отправляйте письма после входа."},
 ar:{brand:"بريد مؤقت",tag:"صندوق مؤقت مع تسجيل دخول وإرسال محدود.",inbox:"الوارد",send:"إرسال",account:"الحساب",admin:"الإدارة",copy:"نسخ",newBox:"جديد",refresh:"تحديث",clear:"مسح",message:"الرسالة",delete:"حذف",noMail:"لا توجد رسائل.",choose:"اختر رسالة.",notice:"تنتهي الرسائل بعد 24 ساعة. من يعرف اسم الصندوق يستطيع قراءته.",sendTitle:"إرسال بريد",from:"من",to:"إلى",subject:"الموضوع",body:"النص",login:"دخول",register:"تسجيل",logout:"خروج",username:"اسم المستخدم",email:"البريد",password:"كلمة المرور",loginId:"اسم المستخدم أو البريد",adminTitle:"نظام الإدارة",role:"الدور",created:"تاريخ الإنشاء",today:"أرسل اليوم",total:"إجمالي الإرسال",phTo:"recipient@example.com",ph主题:"موضوع الرسالة",ph正文:"اكتب رسالتك",signedOut:"لم تسجل الدخول",signedIn:"مسجل باسم {user}",quotaGuest:"حد الضيف: {used}/{limit} اليوم",quotaAdmin:"المدير: بلا حد يومي",must登录:"يجب تسجيل الدخول للإرسال.",sent:"تم الإرسال.",sendFail:"فشل الإرسال: {error}",loading:"جار التحميل...",loginOk:"تم الدخول.",logoutOk:"تم الخروج.",createdOk:"تم إنشاء الحساب.",adminOnly:"صلاحية المدير مطلوبة.",seoTitle:"بريد مؤقت - صندوق بريد مؤقت",seoDescription:"أنشئ بريدًا مؤقتًا واستقبل الرسائل لمدة 24 ساعة وأرسل البريد بعد تسجيل الدخول."},
 es:{brand:"Correo temporal",tag:"Buzón temporal con inicio de sesión y envío limitado.",inbox:"Entrada",send:"Enviar",account:"Cuenta",admin:"Admin",copy:"Copiar",newBox:"Nuevo",refresh:"Actualizar",clear:"Limpiar",message:"Mensaje",delete:"Eliminar",noMail:"Aún no hay correo.",choose:"Elige un mensaje.",notice:"Los mensajes caducan después de 24 horas. Quien conozca el buzón puede leerlo.",sendTitle:"Enviar correo",from:"De",to:"Para",subject:"Asunto",body:"Cuerpo",login:"Entrar",register:"Registrar",logout:"Salir",username:"Usuario",email:"Email",password:"Contraseña",loginId:"Usuario o email",adminTitle:"Sistema admin",role:"Rol",created:"Creado",today:"Enviados hoy",total:"Total enviados",phTo:"recipient@example.com",ph主题:"Asunto",ph正文:"Escribe tu mensaje",signedOut:"Sin sesión",signedIn:"Sesión: {user}",quotaGuest:"Límite: {used}/{limit} hoy",quotaAdmin:"Admin: sin límite diario",must登录:"Debes iniciar sesión para enviar.",sent:"Enviado.",sendFail:"Error al enviar: {error}",loading:"Cargando...",loginOk:"Sesión iniciada.",logoutOk:"Sesión cerrada.",createdOk:"Cuenta creada.",adminOnly:"Se requiere admin.",seoTitle:"Correo temporal - buzón desechable",seoDescription:"Crea un correo temporal, recibe mensajes durante 24 horas y envía correos después de iniciar sesión."},
 "zh-CN":{brand:"临时邮箱",tag:"临时收件箱，支持账号登录和限额发信。",inbox:"收件箱",send:"发邮件",account:"账号",admin:"管理",copy:"复制",newBox:"新建",refresh:"刷新",clear:"清空",message:"信息",delete:"删除",noMail:"还没收到邮件。",choose:"选择一条信息。",notice:"邮件会在 24 小时后自动过期。知道邮箱名前缀的人都可以查看。",sendTitle:"发送邮件",from:"发件人",to:"收件人",subject:"主题",body:"正文",login:"登录",register:"注册",logout:"退出",username:"用户名",email:"邮箱",password:"密码",loginId:"用户名或邮箱",adminTitle:"管理系统",role:"角色",created:"创建时间",today:"今日发送",total:"累计发送",phTo:"recipient@example.com",ph主题:"邮件主题",ph正文:"填写邮件正文",signedOut:"未登录",signedIn:"已登录：{user}",quotaGuest:"游客限额：今日 {used}/{limit}",quotaAdmin:"管理员：无每日发信限制",must登录:"登录后才能发送邮件。",sent:"已发送。",sendFail:"发送失败：{error}",loading:"加载中...",loginOk:"登录成功。",logoutOk:"已退出。",createdOk:"账号已创建。",adminOnly:"需要管理员权限。",code:"验证码",sendCode:"发送验证码",codeSent:"验证码已发送。",attachments:"附件",users:"用户",currentMail:"当前邮件",archives:"归档邮件",seoTitle:"临时邮箱 - 一次性邮件收件箱",seoDescription:"创建临时邮箱，24 小时收信，登录后可发送邮件。"},
 "zh-TW":{brand:"臨時信箱",tag:"臨時收件匣，支援帳號登入與限額寄信。",inbox:"收件匣",send:"寄信",account:"帳號",admin:"管理",copy:"複製",newBox:"新增",refresh:"重新整理",clear:"清空",message:"訊息",delete:"刪除",noMail:"尚未收到郵件。",choose:"選擇一封郵件。",notice:"郵件會在 24 小時後自動過期。知道信箱名稱的人都能查看。",sendTitle:"寄送郵件",from:"寄件者",to:"收件者",subject:"主旨",body:"內容",login:"登入",register:"註冊",logout:"登出",username:"使用者名稱",email:"信箱",password:"密碼",loginId:"使用者名稱或信箱",adminTitle:"管理系統",role:"角色",created:"建立時間",today:"今日寄送",total:"累計寄送",phTo:"recipient@example.com",ph主题:"郵件主旨",ph正文:"輸入郵件內容",signedOut:"尚未登入",signedIn:"已登入：{user}",quotaGuest:"訪客限額：今日 {used}/{limit}",quotaAdmin:"管理員：無每日寄信限制",must登录:"登入後才能寄送郵件。",sent:"已寄出。",sendFail:"寄送失敗：{error}",loading:"載入中...",loginOk:"登入成功。",logoutOk:"已登出。",createdOk:"帳號已建立。",adminOnly:"需要管理員權限。",seoTitle:"臨時信箱 - 一次性電子郵件",seoDescription:"建立臨時信箱，24 小時收信，登入後可寄送郵件。"},
 de:{brand:"Temporäre E-Mail",tag:"Temporäres Postfach mit 登录 und begrenztem Versand.",inbox:"Posteingang",send:"发送en",account:"Konto",admin:"Admin",copy:"Kopieren",newBox:"Neu",refresh:"Aktualisieren",clear:"Leeren",message:"Nachricht",delete:"Löschen",noMail:"Noch keine Mail.",choose:"Nachricht auswählen.",notice:"Nachrichten laufen nach 24 Stunden ab. Wer den Namen kennt, kann sie lesen.",sendTitle:"E-Mail senden",from:"Von",to:"An",subject:"Betreff",body:"Text",login:"登录",register:"Registrieren",logout:"退出",username:"Benutzername",email:"E-Mail",password:"Passwort",loginId:"Benutzername oder E-Mail",adminTitle:"Admin-System",role:"Rolle",created:"Erstellt",today:"Heute gesendet",total:"Gesamt gesendet",phTo:"recipient@example.com",ph主题:"Betreff",ph正文:"Nachricht schreiben",signedOut:"Nicht angemeldet",signedIn:"Angemeldet als {user}",quotaGuest:"Limit: {used}/{limit} heute",quotaAdmin:"Admin: kein Tageslimit",must登录:"Zum 发送en anmelden.",sent:"Gesendet.",sendFail:"发送en fehlgeschlagen: {error}",loading:"Laden...",loginOk:"Angemeldet.",logoutOk:"Abgemeldet.",createdOk:"Konto erstellt.",adminOnly:"Admin-Rechte erforderlich.",seoTitle:"Temporäre E-Mail - Wegwerf-Postfach",seoDescription:"Erstelle ein temporäres Postfach, empfange Nachrichten 24 Stunden und sende E-Mails nach dem 登录."},
 it:{brand:"Email temporanea",tag:"Casella temporanea con accesso e invio limitato.",inbox:"Posta",send:"Invia",account:"Account",admin:"Admin",copy:"Copia",newBox:"Nuova",refresh:"Aggiorna",clear:"Svuota",message:"Messaggio",delete:"Elimina",noMail:"Nessuna email.",choose:"Scegli un messaggio.",notice:"I messaggi scadono dopo 24 ore. Chi conosce il nome può leggerli.",sendTitle:"Invia email",from:"Da",to:"A",subject:"Oggetto",body:"Testo",login:"Accedi",register:"Registrati",logout:"Esci",username:"Utente",email:"Email",password:"密码",loginId:"Utente o email",adminTitle:"Sistema admin",role:"Ruolo",created:"Creato",today:"Inviate oggi",total:"Totale inviate",phTo:"recipient@example.com",ph主题:"Oggetto",ph正文:"Scrivi il messaggio",signedOut:"Non connesso",signedIn:"Accesso: {user}",quotaGuest:"Limite: {used}/{limit} oggi",quotaAdmin:"Admin: nessun limite giornaliero",must登录:"Devi accedere per inviare.",sent:"Inviata.",sendFail:"Invio fallito: {error}",loading:"Caricamento...",loginOk:"Accesso effettuato.",logoutOk:"Uscito.",createdOk:"Account creato.",adminOnly:"Serve admin.",seoTitle:"Email temporanea - casella usa e getta",seoDescription:"Crea una casella email temporanea, ricevi messaggi per 24 ore e invia email dopo il login."},
 fr:{brand:"Email temporaire",tag:"Boîte temporaire avec connexion et envoi limité.",inbox:"Boîte",send:"Envoyer",account:"Compte",admin:"Admin",copy:"Copier",newBox:"Nouveau",refresh:"Actualiser",clear:"Vider",message:"Message",delete:"Supprimer",noMail:"Aucun mail.",choose:"Choisissez un message.",notice:"Les messages expirent après 24 heures. Toute personne qui connaît le nom peut les lire.",sendTitle:"Envoyer un email",from:"De",to:"À",subject:"Sujet",body:"Texte",login:"Connexion",register:"Inscription",logout:"Déconnexion",username:"Nom",email:"Email",password:"Mot de passe",loginId:"Nom ou email",adminTitle:"Administration",role:"Rôle",created:"Créé",today:"Envoyés aujourd'hui",total:"Total envoyés",phTo:"recipient@example.com",ph主题:"Sujet",ph正文:"Votre message",signedOut:"Non connecté",signedIn:"Connecté: {user}",quotaGuest:"Limite: {used}/{limit} aujourd'hui",quotaAdmin:"Admin: aucune limite quotidienne",must登录:"Connexion requise pour envoyer.",sent:"Envoyé.",sendFail:"Échec: {error}",loading:"Chargement...",loginOk:"Connecté.",logoutOk:"Déconnecté.",createdOk:"Compte créé.",adminOnly:"Accès admin requis.",seoTitle:"Email temporaire - boîte jetable",seoDescription:"Créez une adresse temporaire, recevez des messages pendant 24 heures et envoyez après connexion."},
 pt:{brand:"Email temporário",tag:"Caixa temporária com login e envio limitado.",inbox:"Entrada",send:"Enviar",account:"Conta",admin:"Admin",copy:"Copiar",newBox:"Novo",refresh:"Atualizar",clear:"Limpar",message:"Mensagem",delete:"Excluir",noMail:"Sem emails.",choose:"Escolha uma mensagem.",notice:"Mensagens expiram após 24 horas. Quem conhece o nome pode ler.",sendTitle:"Enviar email",from:"De",to:"Para",subject:"Assunto",body:"Texto",login:"Entrar",register:"Registrar",logout:"Sair",username:"Usuário",email:"Email",password:"Senha",loginId:"Usuário ou email",adminTitle:"Administração",role:"Função",created:"Criado",today:"Hoje",total:"Total",phTo:"recipient@example.com",ph主题:"Assunto",ph正文:"Escreva sua mensagem",signedOut:"Sem login",signedIn:"Logado: {user}",quotaGuest:"Limite: {used}/{limit} hoje",quotaAdmin:"Admin: sem limite diário",must登录:"Faça login para enviar.",sent:"Enviado.",sendFail:"Falha: {error}",loading:"Carregando...",loginOk:"登录 feito.",logoutOk:"Sessão encerrada.",createdOk:"Conta criada.",adminOnly:"Admin necessário.",seoTitle:"Email temporário - caixa descartável",seoDescription:"Crie um email temporário, receba mensagens por 24 horas e envie após login."},
 ja:{brand:"一時メール",tag:"ログイン付きの一時受信箱と制限付き送信。",inbox:"受信箱",send:"送信",account:"アカウント",admin:"管理",copy:"コピー",newBox:"新規",refresh:"更新",clear:"クリア",message:"メッセージ",delete:"削除",noMail:"メールはありません。",choose:"メッセージを選択。",notice:"メッセージは24時間後に期限切れになります。名前を知っている人は読めます。",sendTitle:"メール送信",from:"差出人",to:"宛先",subject:"件名",body:"本文",login:"ログイン",register:"登録",logout:"ログアウト",username:"ユーザー名",email:"メール",password:"パスワード",loginId:"ユーザー名またはメール",adminTitle:"管理システム",role:"権限",created:"作成日",today:"本日送信",total:"総送信",phTo:"recipient@example.com",ph主题:"件名",ph正文:"本文を入力",signedOut:"未ログイン",signedIn:"ログイン中: {user}",quotaGuest:"制限: 本日 {used}/{limit}",quotaAdmin:"管理者: 日次制限なし",must登录:"送信にはログインが必要です。",sent:"送信しました。",sendFail:"送信失敗: {error}",loading:"読み込み中...",loginOk:"ログインしました。",logoutOk:"ログアウトしました。",createdOk:"アカウント作成済み。",adminOnly:"管理者権限が必要です。",seoTitle:"一時メール - 使い捨て受信箱",seoDescription:"一時メールを作成し、24時間受信し、ログイン後にメールを送信できます。"},
 ko:{brand:"임시 이메일",tag:"로그인과 제한 발송을 지원하는 임시 받은편지함.",inbox:"받은편지함",send:"보내기",account:"계정",admin:"관리",copy:"복사",newBox:"새로 만들기",refresh:"새로고침",clear:"비우기",message:"메시지",delete:"삭제",noMail:"메일이 없습니다.",choose:"메시지를 선택하세요.",notice:"메시지는 24시간 후 만료됩니다. 이름을 아는 사람은 읽을 수 있습니다.",sendTitle:"메일 보내기",from:"보낸 사람",to:"받는 사람",subject:"제목",body:"본문",login:"로그인",register:"가입",logout:"로그아웃",username:"사용자명",email:"이메일",password:"비밀번호",loginId:"사용자명 또는 이메일",adminTitle:"관리 시스템",role:"역할",created:"생성일",today:"오늘 발송",total:"총 발송",phTo:"recipient@example.com",ph主题:"제목",ph正文:"본문 입력",signedOut:"로그인 안 됨",signedIn:"로그인: {user}",quotaGuest:"한도: 오늘 {used}/{limit}",quotaAdmin:"관리자: 일일 제한 없음",must登录:"발송하려면 로그인하세요.",sent:"보냈습니다.",sendFail:"발송 실패: {error}",loading:"불러오는 중...",loginOk:"로그인했습니다.",logoutOk:"로그아웃했습니다.",createdOk:"계정이 생성되었습니다.",adminOnly:"관리자 권한이 필요합니다.",seoTitle:"임시 이메일 - 일회용 받은편지함",seoDescription:"임시 이메일을 만들고 24시간 동안 수신하며 로그인 후 메일을 보낼 수 있습니다."}
};
const state={box:"",selected:null,messages:[],me:null,lang:"en"};
const $=id=>document.getElementById(id);
const T=(k,v={})=>{let s=(D[state.lang]&&D[state.lang][k])||D.en[k]||k;for(const [a,b] of Object.entries(v))s=s.replaceAll(`{${a}}`,b);return s};
function cleanBox(v){return(v||"").toLowerCase().split("@")[0].replace(/[^a-z0-9._+-]/g,"").slice(0,64)}
function randomBox(){const a=new Uint8Array(8);crypto.getRandomValues(a);return"box"+Array.from(a,x=>x.toString(16).padStart(2,"0")).join("")}
function setBox(b){state.box=cleanBox(b)||randomBox();$("address").value=`${state.box}@${domain}`;location.hash=state.box;localStorage.setItem("tempmail.box",state.box)}
function cleanErr(s){return (s||"").replace(/<script[\s\S]*?<\/script>/gi," ").replace(/<style[\s\S]*?<\/style>/gi," ").replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim().slice(0,700)}
async function api(path,opt={}){opt.credentials="include";opt.headers=Object.assign({"Content-Type":"application/json"},opt.headers||{});const r=await fetch(path,opt);const txt=await r.text();let d={};try{d=txt?JSON.parse(txt):{}}catch(e){d={error:cleanErr(txt)}}if(!r.ok)throw new Error(cleanErr(d.error)||r.statusText);return d}
function res(id,msg,ok=true){const e=$(id);e.textContent=msg||"";e.className="result"+(msg?(ok?" ok":" err"):"")}
function renderList(){const l=$("list");l.innerHTML="";if(!state.messages.length){l.innerHTML=`<div class="empty">${T("noMail")}</div>`;return}for(const m of state.messages){const b=document.createElement("button");b.className="msg"+(m.id===state.selected?" active":"");b.innerHTML='<div class="ms"></div><div class="mm"></div><div class="mm"></div>';b.querySelector(".ms").textContent=m.subject||"(no subject)";const a=b.querySelectorAll(".mm");a[0].textContent=m.sender||"unknown";a[1].textContent=m.received_at||"";b.onclick=()=>openMsg(m.id);l.appendChild(b)}}
function renderReader(m){const r=$("reader");if(!m){r.innerHTML=`<div class="empty">${T("choose")}</div>`;$("delete").disabled=true;return}r.innerHTML="";const h=document.createElement("h2");h.textContent=m.subject||"(no subject)";const meta=document.createElement("div");meta.className="meta";meta.textContent=`${T("from")}: ${m.sender||"unknown"}  ${T("to")}: ${m.recipient||""}  ${m.received_at||""}`;const pre=document.createElement("pre");pre.textContent=m.text||m.raw||"";r.append(h,meta,pre);if(m.attachments&&m.attachments.length){const box=encodeURIComponent(m.mailbox||state.box);const wrap=document.createElement("div");wrap.className="notice";wrap.textContent=T("attachments")+": ";for(const a of m.attachments){const link=document.createElement("a");link.href=`/api/attachment?box=${box}&id=${a.id}`;link.textContent=`${a.filename} (${Math.ceil(a.size/1024)} KB)`;link.style.marginRight="12px";wrap.appendChild(link)}r.appendChild(wrap)}$("delete").disabled=false}async function loadMessages(){if(!state.box)return;try{const d=await api(`/api/messages?box=${encodeURIComponent(state.box)}`,{headers:{}});state.messages=d.messages||[];renderList()}catch(e){$("pill").textContent=T("connectionError")}}
async function openMsg(id){state.selected=id;renderList();try{const m=await api(`/api/message?box=${encodeURIComponent(state.box)}&id=${id}`,{headers:{}});renderReader(m)}catch(e){renderReader(null);await loadMessages()}}
function applyLang(lang){state.lang=D[lang]?lang:"en";localStorage.setItem("tempmail.lang",state.lang);document.documentElement.lang=state.lang;document.documentElement.dir=state.lang==="ar"?"rtl":"ltr";document.title=T("seoTitle");const desc=document.querySelector('meta[name="description"]');if(desc)desc.content=T("seoDescription");document.querySelectorAll("[data-k]").forEach(e=>e.textContent=T(e.dataset.k));document.querySelectorAll("[data-ph]").forEach(e=>e.placeholder=T(e.dataset.ph));renderList();renderReader(null);renderAuth()}
function setupLang(){const s=$("lang");for(const [c,n]of languages){const o=document.createElement("option");o.value=c;o.textContent=n;s.appendChild(o)}const p=new URLSearchParams(location.search);const l=p.get("lang")||localStorage.getItem("tempmail.lang")||navigator.language||"en";const m=languages.find(([c])=>c.toLowerCase()===l.toLowerCase())||languages.find(([c])=>l.toLowerCase().startsWith(c.toLowerCase().split("-")[0]));s.value=m?m[0]:"en";applyLang(s.value);s.onchange=()=>applyLang(s.value)}
function tab(t){document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===t));document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id===`view-${t}`));if(t==="admin")loadUsers()}
function renderAuth(){if(state.me){$("pill").textContent=T("signedIn",{user:state.me.username});res("accountResult",`${T("signedIn",{user:state.me.username})} · ${state.me.email} · ${state.me.role}`,true)}else{$("pill").textContent=T("signedOut");res("accountResult",T("signedOut"),false)}$("adminTab").style.display=state.me&&state.me.role==="admin"?"inline-block":"none";$("logout").disabled=!state.me;render发送()}
function render发送(){$("fromAddr").textContent=state.me?`${state.me.username}@${domain}`:"-";$("sendButton").disabled=!state.me;if(!state.me){$("quota").textContent=T("must登录");return}$("quota").textContent=state.me.role==="admin"?T("quotaAdmin"):T("quotaGuest",{used:state.me.sent_today||0,limit:state.me.daily_limit||10})}
async function loadMe(){try{const d=await api("/api/me",{headers:{}});state.me=d.user||null}catch(e){state.me=null}renderAuth()}
async function loadUsers(){if(!state.me||state.me.role!=="admin"){res("adminResult",T("adminOnly"),false);return}res("adminResult",T("loading"),true);try{const d=await api("/api/admin/users",{headers:{}});const body=$("users正文");body.innerHTML="";for(const u of d.users||[]){const tr=document.createElement("tr");for(const val of [u.username,u.email,u.role,u.created_at,u.sent_today,u.sent_total]){const td=document.createElement("td");td.textContent=val;tr.appendChild(td)}body.appendChild(tr)}const cm=await api("/api/admin/messages",{headers:{}});const mb=$("mail正文");mb.innerHTML="";for(const m of cm.messages||[]){const tr=document.createElement("tr");for(const val of [m.id,m.mailbox,m.sender,m.subject,m.text,m.received_at]){const td=document.createElement("td");td.textContent=val||"";tr.appendChild(td)}mb.appendChild(tr)}const ar=await api("/api/admin/archives",{headers:{}});const ab=$("archive正文");ab.innerHTML="";for(const m of ar.messages||[]){const tr=document.createElement("tr");for(const val of [m.id,m.mailbox,m.sender,m.subject,m.text,m.received_at]){const td=document.createElement("td");td.textContent=val||"";tr.appendChild(td)}ab.appendChild(tr)}res("adminResult",`${(d.users||[]).length} users · ${(cm.messages||[]).length} current · ${(ar.messages||[]).length} archived`,true)}catch(e){res("adminResult",e.message,false)}}
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$("address").addEventListener("change",()=>{setBox($("address").value);state.selected=null;renderReader(null);loadMessages()});
$("copy").onclick=async()=>{await navigator.clipboard.writeText($("address").value);$("pill").textContent="Copied"};
$("newbox").onclick=()=>{setBox(randomBox());state.selected=null;renderReader(null);loadMessages()};
$("refresh").onclick=loadMessages;
$("clear").onclick=async()=>{await api("/api/clear",{method:"POST",body:JSON.stringify({box:state.box})});state.selected=null;renderReader(null);await loadMessages()};
$("delete").onclick=async()=>{if(!state.selected)return;await api("/api/delete",{method:"POST",body:JSON.stringify({box:state.box,id:state.selected})});state.selected=null;renderReader(null);await loadMessages()};
$("loginForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/login",{method:"POST",body:JSON.stringify({login:$("loginId").value,password:$("login密码").value})});res("accountResult",T("loginOk"),true);await loadMe()}catch(err){res("accountResult",err.message,false)}};
$("requestCode").onclick=async()=>{try{res("accountResult",T("loading"),true);await api("/api/request-code",{method:"POST",body:JSON.stringify({email:$("regEmail").value})});res("accountResult",T("codeSent"),true)}catch(err){res("accountResult",err.message,false)}};
$("registerForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/register",{method:"POST",body:JSON.stringify({username:$("regUsername").value,email:$("regEmail").value,password:$("reg密码").value,code:$("regCode").value})});res("accountResult",T("createdOk"),true);await loadMe()}catch(err){res("accountResult",err.message,false)}};
$("logout").onclick=async()=>{await api("/api/logout",{method:"POST",body:"{}"});state.me=null;res("accountResult",T("logoutOk"),true);renderAuth()};
$("sendForm").onsubmit=async e=>{e.preventDefault();res("sendResult",T("loading"),true);try{const d=await api("/api/send",{method:"POST",body:JSON.stringify({to:$("sendTo").value,subject:$("send主题").value,body:$("send正文").value})});res("sendResult",T("sent"),true);state.me=d.user||state.me;render发送()}catch(err){res("sendResult",T("sendFail",{error:err.message}),false);await loadMe()}};
$("reloadUsers").onclick=loadUsers;
setupLang();setBox(location.hash.slice(1)||localStorage.getItem("tempmail.box")||randomBox());loadMe();loadMessages();setInterval(loadMessages,5000);
</script>
</body>
</html>""".replace("__DOMAIN__", DOMAIN).replace("__SEO_KEYWORDS__", html.escape(SEO_KEYWORDS, quote=True))


LEGACY_PUBLIC_PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>???? - Temp Mail</title><meta name="description" content="?????????????????????????????????????????"><meta name="keywords" content="temporary email,temp mail,disposable email,anonymous inbox,free temporary mailbox,temporary mailbox,????,?????,????,????????? ?????,correo temporal,wegwerf email,email temporanea"><meta name="robots" content="index,follow"><link rel="canonical" href="https://__DOMAIN__/"><link rel="alternate" hreflang="en" href="https://__DOMAIN__/?lang=en"><link rel="alternate" hreflang="ru" href="https://__DOMAIN__/?lang=ru"><link rel="alternate" hreflang="ar" href="https://__DOMAIN__/?lang=ar"><link rel="alternate" hreflang="es" href="https://__DOMAIN__/?lang=es"><link rel="alternate" hreflang="zh-CN" href="https://__DOMAIN__/?lang=zh-CN"><link rel="alternate" hreflang="zh-TW" href="https://__DOMAIN__/?lang=zh-TW"><link rel="alternate" hreflang="de" href="https://__DOMAIN__/?lang=de"><link rel="alternate" hreflang="it" href="https://__DOMAIN__/?lang=it"><style>body{margin:0;background:#f6f7f8;color:#151515;font-family:Arial,sans-serif}.w{width:min(1100px,calc(100% - 32px));margin:auto}header{background:white;border-bottom:1px solid #ddd}.top{min-height:80px;display:flex;align-items:center;justify-content:space-between;gap:12px}select,button,input{font:inherit}select,input{min-height:42px;border:1px solid #ddd;border-radius:8px;padding:0 12px;background:#fff}button{min-height:42px;border-radius:8px;border:1px solid #111;background:#111;color:white;font-weight:700;padding:0 14px}button.s{background:white;color:#111}button.d{background:white;color:#c22;border-color:#c22}.bar{display:grid;grid-template-columns:1fr auto auto;gap:10px;margin:22px 0 12px}.g{display:grid;grid-template-columns:330px 1fr;gap:18px}.p{background:white;border:1px solid #ddd;border-radius:8px;overflow:hidden}.h{height:50px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #ddd;font-weight:700}.list,.r{min-height:420px;max-height:68vh;overflow:auto}.r{padding:18px}.e{padding:18px;color:#666}.i{display:block;width:100%;border:0;border-bottom:1px solid #ddd;background:white;text-align:left;padding:12px 14px}.i:hover,.i.on{background:#e9f6f1}.m{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.x{margin-top:6px;color:#666;font-size:13px}.st{color:#666}.ok{color:#087f5b}.err{color:#c22}pre{white-space:pre-wrap;word-break:break-word}a{color:#0b7285}@media(max-width:820px){.top{display:block;padding:16px 0}.top select{margin-top:12px}.bar{grid-template-columns:1fr 1fr}.bar input{grid-column:1/-1}.g{grid-template-columns:1fr}.list,.r{max-height:none;min-height:260px}}</style></head><body><header><div class="w top"><div><h1 id="t1">????</h1><p id="t2" class="st">?????????????????</p></div><div><p id="q" class="st"></p><select id="lang"></select></div></div></header><main class="w"><div class="bar"><input id="addr" spellcheck="false" placeholder="name@__DOMAIN__"><button id="copy">??</button><button class="s" id="new">????</button></div><p id="st" class="st"></p><div class="g"><section class="p"><div class="h"><span id="t3">?????</span><button class="s" id="ref">??</button></div><div id="boxes" class="list"></div></section><section class="p"><div class="h"><span id="t4">???</span><button class="d" id="del" disabled>????</button></div><div id="read" class="r"></div></section></div><p id="t5" class="st">?????????? 5 ????????????????????????? IP ?????????????</p></main><script>const D='__DOMAIN__',LS='tm.boxes',LC='tm.current',$=id=>document.getElementById(id),L=[['zh-CN','????'],['zh-TW','????'],['en','English'],['ru','???????'],['ar','???????'],['es','Espa?ol'],['de','Deutsch'],['it','Italiano'],['fr','Fran?ais'],['pt','Portugu?s'],['ja','???'],['ko','???']],I={'zh-CN':['????','?????????????????','?????','???','?????????? 5 ????????????????????????? IP ?????????????','??','????','??','????','????????','?????????','???????','????...','????? '],'zh-TW':['????','?????????????????','?????','???','?????????? 5 ??????????????????????? IP?','??','????','????','????','???????','?????????','???????','???...','????? '],en:['Temp Mail','Create a temporary mailbox and receive messages with attachments.','Mailboxes on this device','Inbox','Each device can create up to 5 mailboxes per day. Custom local parts are supported. Device fingerprint and IP are recorded for limit enforcement.','Copy','Create mailbox','Refresh','Delete message','No mailbox created yet.','Create or choose a mailbox.','No mail yet.','Creating...','Created today '],ru:['????????? ?????','???????? ????????? ???? ? ????????? ?????? ? ??????????.','????? ??????????','????????','?? 5 ?????? ? ???? ?? ??????????. ?????????????? ???? ?????. ????????? ?????????? ? IP ????????????.','??????????','??????? ????','????????','??????? ??????','?????? ???? ???.','???????? ??? ???????? ????.','????? ???? ???.','????????...','??????? ??????? '],ar:['???? ????','???? ????? ???? ???? ??????? ??????? ?????????.','?????? ??????','??????','??? 5 ?????? ????? ??? ????. ???? ?????? ?????. ??? ????? ?????? ? IP.','???','????? ????','?????','??? ???????','?? ???? ????? ???.','???? ?? ???? ??????.','?? ???? ?????.','??? ???????...','?? ??????? ????? '],es:['Correo temporal','Crea un buz?n temporal y recibe mensajes con adjuntos.','Buzones del dispositivo','Bandeja','Hasta 5 buzones por d?a por dispositivo. Se admite direcci?n personalizada. Se registran huella e IP.','Copiar','Crear buz?n','Actualizar','Eliminar correo','A?n no hay buzones.','Crea o elige un buz?n.','Sin correos todav?a.','Creando...','Creados hoy '],de:['Tempor?re E-Mail','Erstelle ein tempor?res Postfach und empfange Nachrichten mit Anh?ngen.','Postf?cher dieses Ger?ts','Posteingang','Bis zu 5 Postf?cher pro Ger?t und Tag. Eigene Adresse wird unterst?tzt. Fingerabdruck und IP werden gespeichert.','Kopieren','Postfach erstellen','Aktualisieren','E-Mail l?schen','Noch kein Postfach.','Postfach erstellen oder ausw?hlen.','Noch keine Mail.','Erstelle...','Heute erstellt '],it:['Email temporanea','Crea una casella temporanea e ricevi messaggi con allegati.','Caselle del dispositivo','Posta in arrivo','Fino a 5 caselle al giorno per dispositivo. ? supportato un indirizzo personalizzato. Impronta e IP sono registrati.','Copia','Crea casella','Aggiorna','Elimina messaggio','Nessuna casella ancora.','Crea o scegli una casella.','Nessun messaggio.','Creazione...','Create oggi '],fr:['Email temporaire','Create a temporary mailbox and receive messages with attachments.','Mailboxes on this device','Inbox','Each device can create up to 5 mailboxes per day. Custom local parts are supported. Device fingerprint and IP are recorded for limit enforcement.','Copy','Create mailbox','Refresh','Delete message','No mailbox created yet.','Create or choose a mailbox.','No mail yet.','Creating...','Created today '],pt:['Email tempor?rio','Create a temporary mailbox and receive messages with attachments.','Mailboxes on this device','Inbox','Each device can create up to 5 mailboxes per day. Custom local parts are supported. Device fingerprint and IP are recorded for limit enforcement.','Copy','Create mailbox','Refresh','Delete message','No mailbox created yet.','Create or choose a mailbox.','No mail yet.','Creating...','Created today '],ja:['?????','Create a temporary mailbox and receive messages with attachments.','Mailboxes on this device','Inbox','Each device can create up to 5 mailboxes per day. Custom local parts are supported. Device fingerprint and IP are recorded for limit enforcement.','Copy','Create mailbox','Refresh','Delete message','No mailbox created yet.','Create or choose a mailbox.','No mail yet.','Creating...','Created today '],ko:['?? ???','Create a temporary mailbox and receive messages with attachments.','Mailboxes on this device','Inbox','Each device can create up to 5 mailboxes per day. Custom local parts are supported. Device fingerprint and IP are recorded for limit enforcement.','Copy','Create mailbox','Refresh','Delete message','No mailbox created yet.','Create or choose a mailbox.','No mail yet.','Creating...','Created today ']};let B=[],C=null,MS=[],M=null,FP='',LANG='zh-CN';function tr(n){return(I[LANG]||I.en)[n]}function ce(s){return String(s||'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,500)}async function api(u,o={}){o.credentials='include';o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});let r=await fetch(u,o),t=await r.text(),d={};try{d=t?JSON.parse(t):{}}catch(e){d={error:ce(t)}}if(!r.ok)throw Error(ce(d.error)||r.statusText);return d}async function fp(){let raw=[navigator.userAgent,navigator.language,screen.width+'x'+screen.height,Intl.DateTimeFormat().resolvedOptions().timeZone,navigator.platform,navigator.hardwareConcurrency||''].join('|');let b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,'0')).join('')}function load(){try{B=JSON.parse(localStorage.getItem(LS)||'[]')}catch(e){B=[]}let c=localStorage.getItem(LC);C=B.find(x=>x.box===c)||B[0]||null}function save(){localStorage.setItem(LS,JSON.stringify(B));if(C)localStorage.setItem(LC,C.box)}function applyLang(v){LANG=I[v]?v:'zh-CN';localStorage.setItem('tm.lang',LANG);document.documentElement.lang=LANG;document.documentElement.dir=LANG==='ar'?'rtl':'ltr';$('t1').textContent=tr(0);$('t2').textContent=tr(1);$('t3').textContent=tr(2);$('t4').textContent=tr(3);$('t5').textContent=tr(4);$('copy').textContent=tr(5);$('new').textContent=tr(6);$('ref').textContent=tr(7);$('del').textContent=tr(8);render()}function status(s,c=''){let e=$('st');e.textContent=s||'';e.className='st '+c}function render(){let b=$('boxes');b.innerHTML='';if(!B.length)b.innerHTML=`<div class=e>${tr(9)}</div>`;for(const x of B){let n=document.createElement('button');n.className='i '+(C&&C.box===x.box?'on':'');n.innerHTML='<div class=m></div><div class=x></div>';n.querySelector('.m').textContent=x.address;n.querySelector('.x').textContent=x.created_at||'';n.onclick=()=>{C=x;M=null;save();refresh()};b.appendChild(n)}$('addr').value=C?C.address:'';$('del').disabled=!M;let r=$('read');if(!C){r.innerHTML=`<div class=e>${tr(10)}</div>`;return}if(M){r.innerHTML='';let h=document.createElement('h2');h.textContent=M.subject||'(no subject)';let p=document.createElement('p');p.className='st';p.textContent=`From: ${M.sender||''} To: ${M.recipient||''} ${M.received_at||''}`;let pre=document.createElement('pre');pre.textContent=M.text||M.raw||'';r.append(h,p,pre);for(const a of M.attachments||[]){let l=document.createElement('a');l.href=`/api/attachment?box=${encodeURIComponent(C.box)}&token=${encodeURIComponent(C.token)}&id=${a.id}`;l.textContent=`${a.filename} (${Math.ceil(a.size/1024)} KB)`;r.append(document.createElement('br'),l)}return}if(!MS.length){r.innerHTML=`<div class=e>${tr(11)}</div>`;return}r.innerHTML='';for(const m of MS){let n=document.createElement('button');n.className='i';n.innerHTML='<div class=m></div><div class=x></div><div class=x></div>';n.querySelector('.m').textContent=m.subject||'(no subject)';let xs=n.querySelectorAll('.x');xs[0].textContent=m.sender||'';xs[1].textContent=m.received_at||'';n.onclick=()=>openMsg(m.id);r.appendChild(n)}}async function refresh(){render();if(!C)return;try{let d=await api(`/api/messages?box=${encodeURIComponent(C.box)}&token=${encodeURIComponent(C.token)}`,{headers:{}});MS=d.messages||[];M=null;render();status('')}catch(e){status(e.message,'err')}}async function openMsg(id){M=await api(`/api/message?box=${encodeURIComponent(C.box)}&token=${encodeURIComponent(C.token)}&id=${id}`,{headers:{}});render()}$('new').onclick=async()=>{try{let raw=$('addr').value.trim(),same=C&&raw&&raw.toLowerCase()===C.address.toLowerCase(),body={fingerprint:FP};if(raw&&!same)body.box=raw;status(tr(12));let d=await api('/api/create-mailbox',{method:'POST',body:JSON.stringify(body)});let x={box:d.box,address:d.address,token:d.token,created_at:d.created_at};B=B.filter(v=>v.box!==x.box);B.unshift(x);C=x;save();$('q').textContent=tr(13)+`${d.used}/${d.limit}`;status(d.address,'ok');refresh()}catch(e){status(e.message,'err')}};$('copy').onclick=()=>{if($('addr').value)navigator.clipboard.writeText($('addr').value)};$('ref').onclick=refresh;$('del').onclick=async()=>{if(C&&M){await api('/api/delete',{method:'POST',body:JSON.stringify({box:C.box,token:C.token,id:M.id})});refresh()}};for(const [c,n] of L){let o=document.createElement('option');o.value=c;o.textContent=n;$('lang').appendChild(o)}$('lang').onchange=e=>applyLang(e.target.value);(async()=>{FP=await fp().catch(()=>'unavailable');load();let q=new URLSearchParams(location.search).get('lang')||localStorage.getItem('tm.lang')||'zh-CN';$('lang').value=L.find(v=>v[0]===q)?q:'zh-CN';applyLang($('lang').value);refresh();setInterval(refresh,8000)})();</script></body></html>""".replace("__DOMAIN__", DOMAIN)
ADMIN_PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>emali.net 管理后台</title><meta name="robots" content="noindex,nofollow"><style>body{margin:0;background:#f6f7f8;color:#151515;font-family:Arial,sans-serif}.w{width:min(1240px,calc(100% - 32px));margin:auto}header{background:white;border-bottom:1px solid #ddd}.top{min-height:76px;display:flex;align-items:center;justify-content:space-between}.p{background:white;border:1px solid #ddd;border-radius:8px;margin:18px 0;overflow:hidden}.h{height:50px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #ddd;font-weight:700}.b{padding:16px}.g{display:grid;grid-template-columns:360px 1fr;gap:18px}label{display:grid;gap:6px;margin-bottom:12px;font-weight:700}input,textarea{min-height:42px;border:1px solid #ddd;border-radius:8px;padding:8px 12px;font:inherit}textarea{min-height:140px}button{min-height:40px;border:1px solid #111;border-radius:8px;background:#111;color:white;font-weight:700;padding:0 14px}button.s{background:white;color:#111}.hide{display:none}.st{color:#666}.ok{color:#087f5b}.err{color:#c22}.scroll{overflow:auto;max-height:520px}table{width:100%;border-collapse:collapse;background:white}td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top;font-size:13px;word-break:break-word}th{color:#666}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:900px){.top{display:block;padding:16px 0}.g{grid-template-columns:1fr}.scroll{max-height:none}}</style></head><body><header><div class="w top"><div><h1>emali.net 管理后台</h1><p class="st">管理员登录、无限发信、邮件与设备信息审计。</p></div><button class="s hide" id="logout">退出</button></div></header><main class="w"><section class="p" id="loginBox"><div class="h">管理员登录</div><div class="b"><form id="loginForm"><label>用户名或邮箱<input id="login"></label><label>密码<input id="pw" type="password"></label><button>登录</button></form><p id="loginSt" class="st"></p></div></section><section id="dash" class="hide"><div class="g"><section class="p"><div class="h">发送邮件</div><div class="b"><form id="sendForm"><label>发件地址前缀<input id="from" placeholder="a / ab / abc / admin"></label><label>收件人<input id="to"></label><label>主题<input id="sub"></label><label>正文<textarea id="body"></textarea></label><button>发送</button></form><p id="sendSt" class="st"></p></div></section><section class="p"><div class="h"><span>邮件详情</span><button class="s" id="reload">刷新</button></div><div class="b" id="detail">选择一封邮件查看内容和附件。</div></section></div><section class="p"><div class="h">项目运行以来接收的邮件</div><div class="scroll"><table><thead><tr><th>Source</th><th>ID</th><th>Mailbox</th><th>发送er</th><th>主题</th><th>Time</th><th>Files</th><th>IP</th><th>Fingerprint</th><th>Action</th></tr></thead><tbody id="msgs"></tbody></table></div></section><section class="p"><div class="h">邮箱创建记录</div><div class="scroll"><table><thead><tr><th>ID</th><th>Mailbox</th><th>Owner</th><th>Created</th><th>Date</th><th>IP</th><th>Fingerprint</th><th>User-Agent</th></tr></thead><tbody id="boxes"></tbody></table></div></section></section></main><script>const $=id=>document.getElementById(id);function ce(s){return String(s||'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,700)}async function api(u,o={}){o.credentials='include';o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});let r=await fetch(u,o),t=await r.text(),d={};try{d=t?JSON.parse(t):{}}catch(e){d={error:ce(t)}}if(!r.ok)throw Error(ce(d.error)||r.statusText);return d}function show(x){$('loginBox').classList.toggle('hide',x);$('dash').classList.toggle('hide',!x);$('logout').classList.toggle('hide',!x)}function st(id,msg,ok){let e=$(id);e.textContent=msg||'';e.className='st '+(msg?(ok?'ok':'err'):'')}function td(tr,v){let d=document.createElement('td');d.textContent=v==null?'':String(v);tr.appendChild(d)}async function me(){try{let d=await api('/api/me',{headers:{}});show(!!(d.user&&d.user.role==='admin'));if(d.user)load()}catch(e){show(false)}}async function load(){let d=await api('/api/admin/messages',{headers:{}}),b=$('msgs');b.innerHTML='';for(const m of d.messages||[]){let tr=document.createElement('tr');[m.source,m.id,m.mailbox,m.sender,m.subject,m.received_at,m.attachments,m.ip,m.fingerprint].forEach(v=>td(tr,v));let x=document.createElement('td'),bt=document.createElement('button');bt.className='s';bt.textContent='查看';bt.onclick=()=>openMsg(m.source,m.id);x.appendChild(bt);tr.appendChild(x);b.appendChild(tr)}let bs=await api('/api/admin/mailboxes',{headers:{}}),tb=$('boxes');tb.innerHTML='';for(const m of bs.mailboxes||[]){let tr=document.createElement('tr');[m.id,m.mailbox,m.created_by,m.created_at,m.local_date,m.ip,m.fingerprint,m.user_agent].forEach(v=>td(tr,v));tb.appendChild(tr)}}async function openMsg(src,id){let m=await api(`/api/admin/message?source=${src}&id=${id}`,{headers:{}}),d=$('detail');d.innerHTML='';let h=document.createElement('h2');h.textContent=m.subject||'(no subject)';let p=document.createElement('p');p.className='st';p.textContent=`source:${m.source} mailbox:${m.mailbox} sender:${m.sender||''} time:${m.received_at||''} ip:${m.ip||''} fingerprint:${m.fingerprint||''}`;let pre=document.createElement('pre');pre.textContent=m.text||m.raw||'';d.append(h,p,pre);for(const a of m.attachments||[]){let l=document.createElement('a');l.href=`/api/admin/attachment?source=${src}&id=${a.id}`;l.textContent=`${a.filename} (${Math.ceil(a.size/1024)} KB)`;d.append(document.createElement('br'),l)}}$('loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/login',{method:'POST',body:JSON.stringify({login:$('login').value,password:$('pw').value})});st('loginSt','登录成功',true);me()}catch(x){st('loginSt',x.message,false)}};$('logout').onclick=async()=>{await api('/api/logout',{method:'POST',body:'{}'});show(false)};$('reload').onclick=load;$('sendForm').onsubmit=async e=>{e.preventDefault();try{let d=await api('/api/send',{method:'POST',body:JSON.stringify({fromLocal:$('from').value,to:$('to').value,subject:$('sub').value,body:$('body').value})});st('sendSt','发送成功 '+((d.result&&d.result.mx)||''),true);load()}catch(x){st('sendSt',x.message,false)}};me();</script></body></html>"""
FINAL_PUBLIC_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Temp Mail</title>
<meta name="description" content="Create a temporary mailbox and receive messages for 24 hours.">
<meta name="robots" content="index,follow">
<style>
:root{color-scheme:light;--ink:#151515;--muted:#5f6368;--line:#d7dce2;--bg:#f4f6f8;--surface:#fff;--soft:#e9f6f1;--danger:#c92a2a}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}header{border-bottom:1px solid var(--line);background:#fff}.wrap{width:min(1080px,calc(100% - 32px));margin:0 auto}.top{min-height:80px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px}.tag{margin:6px 0 0;color:var(--muted);font-size:14px}.tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}.pill{margin:0;color:var(--muted);font-size:14px}select,input{border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);font:inherit}select{min-height:40px;padding:0 10px}main{padding:22px 0 36px}.bar{display:grid;grid-template-columns:1fr auto auto auto;gap:10px;align-items:center;margin-bottom:16px}.addr{width:100%;min-height:46px;padding:0 12px;font-size:18px}button{min-height:44px;border:1px solid var(--ink);border-radius:8px;padding:0 15px;background:var(--ink);color:#fff;cursor:pointer;font-weight:700}button.secondary{background:#fff;color:var(--ink)}button.danger{background:#fff;color:var(--danger);border-color:var(--danger)}button:disabled{opacity:.55;cursor:not-allowed}.grid{display:grid;grid-template-columns:360px 1fr;gap:18px}.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}.head{min-height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--line);font-weight:700}.list,.reader{min-height:480px;max-height:65vh;overflow:auto}.reader{padding:18px}.empty{padding:22px;color:var(--muted);line-height:1.5}.msg{width:100%;display:block;padding:12px 14px;border:0;border-bottom:1px solid var(--line);background:#fff;color:var(--ink);text-align:start;cursor:pointer;border-radius:0;min-height:76px}.msg:hover,.msg.active{background:var(--soft)}.ms{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mm{margin-top:6px;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{color:var(--muted);font-size:14px;line-height:1.5;margin-bottom:16px;word-break:break-word}.notice{margin-top:12px;color:var(--muted);font-size:13px;line-height:1.45}.status{margin-bottom:14px;color:var(--muted);font-size:14px}.status.err{color:var(--danger)}.status.ok{color:#087f5b}pre{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;font-family:Consolas,Menlo,monospace;font-size:14px;line-height:1.5;margin:0}a{color:#0b7285;text-decoration:none}@media(max-width:860px){.top{grid-template-columns:1fr;padding:16px 0}.tools{justify-content:flex-start}.bar{grid-template-columns:1fr 1fr}.addr{grid-column:1/-1;font-size:16px}.grid{grid-template-columns:1fr}.list,.reader{max-height:none;min-height:260px}}
</style>
</head>
<body>
<header><div class="wrap top"><div><h1 id="brand"></h1><p class="tag" id="tag"></p></div><div class="tools"><p class="pill" id="quota"></p><select id="lang"></select></div></div></header>
<main class="wrap"><div class="bar"><input class="addr" id="addr" autocomplete="off" spellcheck="false" placeholder="name@__DOMAIN__"><button id="copy"></button><button class="secondary" id="create"></button><button class="secondary" id="refresh"></button></div><div class="status" id="status"></div><div class="grid"><section class="panel"><div class="head"><span id="boxesTitle"></span><button class="danger" id="clear"></button></div><div class="list" id="boxes"></div></section><section class="panel"><div class="head"><span id="inboxTitle"></span><button class="danger" id="delete"></button></div><div class="reader" id="reader"></div></section></div><p class="notice" id="policy"></p></main>
<script>
const domain="__DOMAIN__";
const LS_BOXES="tm.boxes",LS_CURRENT="tm.current",LS_LANG="tm.lang";
const $=id=>document.getElementById(id);
const languages=[["en","English"],["zh-CN","????"],["zh-TW","????"],["ru","???????"],["ar","???????"],["es","Espa?ol"],["de","Deutsch"],["it","Italiano"],["fr","Fran?ais"],["pt","Portugu?s"],["ja","???"],["ko","???"]];
const I={
"en":{brand:"Temp Mail",tag:"Create a temporary mailbox and receive messages for 24 hours.",boxes:"Mailboxes on this device",inbox:"Inbox",policy:"Each device can create up to 5 mailboxes per day. Anyone with the mailbox token can read or clear that inbox.",copy:"Copy",create:"Create",refresh:"Refresh",clear:"Clear",delete:"Delete",noBoxes:"No mailbox created yet.",choose:"Create or choose a mailbox.",noMail:"No mail yet.",creating:"Creating...",today:"Created today {used}/{limit}",copied:"Address copied.",loading:"Loading...",loadFail:"Failed to load messages.",from:"From",to:"To",attachments:"Attachments"},
"zh-CN":{brand:"????",tag:"???????24 ????????",boxes:"???????",inbox:"???",policy:"?????????? 5 ??????????? token ???????????????",copy:"??",create:"??",refresh:"??",clear:"??",delete:"??",noBoxes:"????????",choose:"????????????",noMail:"???????",creating:"???...",today:"????? {used}/{limit}",copied:"??????",loading:"???...",loadFail:"???????",from:"???",to:"???",attachments:"??"},
"zh-TW":{brand:"????",tag:"???????24 ????????",boxes:"???????",inbox:"???",policy:"??????????? 5 ??????????? token ????????????",copy:"??",create:"??",refresh:"????",clear:"??",delete:"??",noBoxes:"???????",choose:"????????????",noMail:"???????",creating:"???...",today:"????? {used}/{limit}",copied:"??????",loading:"???...",loadFail:"???????",from:"???",to:"???",attachments:"??"},
"ru":{brand:"????????? ?????",tag:"???????? ????????? ???? ? ????????? ?????? 24 ????.",boxes:"????? ?? ???? ??????????",inbox:"????????",policy:"?? ????? ?????????? ????? ??????? ?? 5 ?????? ? ????. ?????, ? ???? ???? ????? ?????, ????? ?????? ? ??????? ???.",copy:"??????????",create:"???????",refresh:"????????",clear:"????????",delete:"???????",noBoxes:"????? ??? ?? ???????.",choose:"???????? ??? ???????? ????.",noMail:"????? ???? ???.",creating:"????????...",today:"??????? ??????? {used}/{limit}",copied:"????? ??????????.",loading:"????????...",loadFail:"?? ??????? ????????? ??????.",from:"??",to:"????",attachments:"????????"},
"ar":{brand:"???? ????",tag:"???? ??????? ?????? ??????? ??????? ???? 24 ????.",boxes:"???????? ??? ??? ??????",inbox:"??????",policy:"???? ??? ???? ????? ??? 5 ?????? ??????. ?? ??? ???? ??? ??????? ????? ????? ??????? ?? ????.",copy:"???",create:"?????",refresh:"?????",clear:"???",delete:"???",noBoxes:"?? ???? ?????? ???.",choose:"???? ??????? ?? ???? ??????.",noMail:"?? ???? ????? ???.",creating:"???? ???????...",today:"?? ??????? ????? {used}/{limit}",copied:"?? ??? ???????.",loading:"???? ???????...",loadFail:"???? ????? ???????.",from:"??",to:"???",attachments:"????????"},
"es":{brand:"Correo temporal",tag:"Crea un buz?n temporal y recibe mensajes durante 24 horas.",boxes:"Buzones en este dispositivo",inbox:"Entrada",policy:"Cada dispositivo puede crear hasta 5 buzones por d?a. Cualquiera con el token del buz?n puede leerlo o vaciarlo.",copy:"Copiar",create:"Crear",refresh:"Actualizar",clear:"Vaciar",delete:"Eliminar",noBoxes:"A?n no hay buzones.",choose:"Crea o elige un buz?n.",noMail:"A?n no hay correos.",creating:"Creando...",today:"Creados hoy {used}/{limit}",copied:"Direcci?n copiada.",loading:"Cargando...",loadFail:"No se pudieron cargar los mensajes.",from:"De",to:"Para",attachments:"Adjuntos"},
"de":{brand:"Tempor?re E-Mail",tag:"Erstelle ein tempor?res Postfach und empfange 24 Stunden lang Nachrichten.",boxes:"Postf?cher auf diesem Ger?t",inbox:"Posteingang",policy:"Jedes Ger?t kann bis zu 5 Postf?cher pro Tag erstellen. Jeder mit dem Postfach-Token kann es lesen oder leeren.",copy:"Kopieren",create:"Erstellen",refresh:"Aktualisieren",clear:"Leeren",delete:"L?schen",noBoxes:"Noch kein Postfach erstellt.",choose:"Erstelle oder w?hle ein Postfach.",noMail:"Noch keine E-Mails.",creating:"Erstelle...",today:"Heute erstellt {used}/{limit}",copied:"Adresse kopiert.",loading:"Laden...",loadFail:"Nachrichten konnten nicht geladen werden.",from:"Von",to:"An",attachments:"Anh?nge"},
"it":{brand:"Email temporanea",tag:"Crea una casella temporanea e ricevi messaggi per 24 ore.",boxes:"Caselle su questo dispositivo",inbox:"Posta in arrivo",policy:"Ogni dispositivo pu? creare fino a 5 caselle al giorno. Chiunque abbia il token pu? leggerla o svuotarla.",copy:"Copia",create:"Crea",refresh:"Aggiorna",clear:"Svuota",delete:"Elimina",noBoxes:"Nessuna casella ancora creata.",choose:"Crea o scegli una casella.",noMail:"Nessun messaggio.",creating:"Creazione...",today:"Create oggi {used}/{limit}",copied:"Indirizzo copiato.",loading:"Caricamento...",loadFail:"Impossibile caricare i messaggi.",from:"Da",to:"A",attachments:"Allegati"},
"fr":{brand:"Email temporaire",tag:"Cr?ez une bo?te temporaire et recevez des messages pendant 24 heures.",boxes:"Bo?tes sur cet appareil",inbox:"Bo?te de r?ception",policy:"Chaque appareil peut cr?er jusqu'? 5 bo?tes par jour. Toute personne ayant le token peut la lire ou la vider.",copy:"Copier",create:"Cr?er",refresh:"Actualiser",clear:"Vider",delete:"Supprimer",noBoxes:"Aucune bo?te cr??e.",choose:"Cr?ez ou choisissez une bo?te.",noMail:"Aucun message.",creating:"Cr?ation...",today:"Cr??es aujourd'hui {used}/{limit}",copied:"Adresse copi?e.",loading:"Chargement...",loadFail:"Impossible de charger les messages.",from:"De",to:"?",attachments:"Pi?ces jointes"},
"pt":{brand:"Email tempor?rio",tag:"Crie uma caixa tempor?ria e receba mensagens por 24 horas.",boxes:"Caixas neste dispositivo",inbox:"Entrada",policy:"Cada dispositivo pode criar at? 5 caixas por dia. Qualquer pessoa com o token pode ler ou limpar essa caixa.",copy:"Copiar",create:"Criar",refresh:"Atualizar",clear:"Limpar",delete:"Excluir",noBoxes:"Nenhuma caixa criada ainda.",choose:"Crie ou escolha uma caixa.",noMail:"Nenhum email ainda.",creating:"Criando...",today:"Criadas hoje {used}/{limit}",copied:"Endere?o copiado.",loading:"Carregando...",loadFail:"Falha ao carregar mensagens.",from:"De",to:"Para",attachments:"Anexos"},
"ja":{brand:"?????",tag:"??????????????24?????????????",boxes:"????????????",inbox:"???",policy:"1 ????? 1 ???? 5 ??????????token ???????????????????",copy:"???",create:"??",refresh:"??",clear:"???",delete:"??",noBoxes:"????????????????",choose:"??????????????????????",noMail:"????????????",creating:"???...",today:"?????? {used}/{limit}",copied:"?????????????",loading:"?????...",loadFail:"????????????????",from:"???",to:"??",attachments:"??????"},
"ko":{brand:"?? ???",tag:"?? ???? ??? 24?? ?? ??? ?? ? ????.",boxes:"? ??? ???",inbox:"?????",policy:"??? ?? ?? 5?? ???? ?? ? ????. token ? ??? ??? ?? ? ????.",copy:"??",create:"???",refresh:"????",clear:"???",delete:"??",noBoxes:"?? ???? ????.",choose:"???? ???? ?????.",noMail:"?? ??? ????.",creating:"?? ?...",today:"?? ?? {used}/{limit}",copied:"??? ??????.",loading:"???? ?...",loadFail:"??? ???? ?????.",from:"?? ??",to:"?? ??",attachments:"?? ??"}
};
const state={boxes:[],current:null,messages:[],selected:null,full:null,fingerprint:"",lang:"en"};
function t(k, vars={}){let s=(I[state.lang]&&I[state.lang][k])||I.en[k]||k;for(const [a,b] of Object.entries(vars))s=s.replaceAll(`{${a}}`, String(b));return s}
function cleanErr(s){return String(s||"").replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim().slice(0,500)}
async function api(u,o={}){o.credentials="include";o.headers=Object.assign({"Content-Type":"application/json"},o.headers||{});const r=await fetch(u,o),txt=await r.text();let d={};try{d=txt?JSON.parse(txt):{}}catch(e){d={error:cleanErr(txt)}}if(!r.ok)throw new Error(cleanErr(d.error)||r.statusText);return d}
async function fp(){const raw=[navigator.userAgent,navigator.language,screen.width+'x'+screen.height,Intl.DateTimeFormat().resolvedOptions().timeZone,navigator.platform,navigator.hardwareConcurrency||''].join('|');const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,'0')).join('')}
function save(){localStorage.setItem(LS_BOXES,JSON.stringify(state.boxes));localStorage.setItem(LS_CURRENT,state.current?state.current.box:'')}
function load(){try{state.boxes=JSON.parse(localStorage.getItem(LS_BOXES)||'[]')}catch(e){state.boxes=[]}const current=localStorage.getItem(LS_CURRENT)||'';state.current=state.boxes.find(x=>x.box===current)||state.boxes[0]||null}
function status(msg,kind=''){const e=$('status');e.textContent=msg||'';e.className='status'+(kind?(' '+kind):'')}
function renderChrome(){$('brand').textContent=t('brand');$('tag').textContent=t('tag');$('boxesTitle').textContent=t('boxes');$('inboxTitle').textContent=t('inbox');$('policy').textContent=t('policy');$('copy').textContent=t('copy');$('create').textContent=t('create');$('refresh').textContent=t('refresh');$('clear').textContent=t('clear');$('delete').textContent=t('delete')}
function renderBoxes(){const list=$('boxes');list.innerHTML='';if(!state.boxes.length){list.innerHTML=`<div class="empty">${t('noBoxes')}</div>`;return}for(const box of state.boxes){const btn=document.createElement('button');btn.className='msg'+(state.current&&state.current.box===box.box?' active':'');btn.innerHTML='<div class="ms"></div><div class="mm"></div>';btn.querySelector('.ms').textContent=box.address;btn.querySelector('.mm').textContent=box.created_at||'';btn.onclick=()=>{state.current=box;state.selected=null;state.full=null;save();render();loadMessages()};list.appendChild(btn)}$('addr').value=state.current?state.current.address:''}
function renderReader(){const reader=$('reader');$('clear').disabled=!state.current;$('delete').disabled=!state.selected;if(!state.current){reader.innerHTML=`<div class="empty">${t('choose')}</div>`;return}if(state.full){const m=state.full;reader.innerHTML='';const h=document.createElement('h2');h.textContent=m.subject||'(no subject)';const meta=document.createElement('div');meta.className='meta';meta.textContent=`${t('from')}: ${m.sender||'unknown'}  ${t('to')}: ${m.recipient||''}  ${m.received_at||''}`;const pre=document.createElement('pre');pre.textContent=m.text||m.raw||'';reader.append(h,meta,pre);if(m.attachments&&m.attachments.length){const wrap=document.createElement('div');wrap.className='notice';wrap.textContent=t('attachments')+': ';for(const a of m.attachments){const link=document.createElement('a');link.href=`/api/attachment?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}&id=${a.id}`;link.textContent=`${a.filename} (${Math.ceil(a.size/1024)} KB)`;link.style.marginRight='12px';wrap.appendChild(link)}reader.appendChild(wrap)}return}if(!state.messages.length){reader.innerHTML=`<div class="empty">${t('noMail')}</div>`;return}reader.innerHTML='';for(const m of state.messages){const btn=document.createElement('button');btn.className='msg'+(m.id===state.selected?' active':'');btn.innerHTML='<div class="ms"></div><div class="mm"></div><div class="mm"></div>';btn.querySelector('.ms').textContent=m.subject||'(no subject)';const meta=btn.querySelectorAll('.mm');meta[0].textContent=m.sender||'unknown';meta[1].textContent=m.received_at||'';btn.onclick=()=>openMessage(m.id);reader.appendChild(btn)}}
function render(){renderChrome();renderBoxes();renderReader()}
async function loadMessages(){if(!state.current){render();return}try{const d=await api(`/api/messages?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}`,{headers:{}});state.messages=d.messages||[];state.selected=null;state.full=null;render();status('')}catch(e){state.messages=[];state.selected=null;state.full=null;render();status(e.message||t('loadFail'),'err')}}
async function openMessage(id){state.selected=id;state.full=null;render();try{state.full=await api(`/api/message?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}&id=${id}`,{headers:{}});render()}catch(e){status(e.message,'err')}}
async function createMailbox(){try{status(t('creating'));const raw=$('addr').value.trim();const body={fingerprint:state.fingerprint};if(raw)body.box=raw;const d=await api('/api/create-mailbox',{method:'POST',body:JSON.stringify(body)});const entry={box:d.box,address:d.address,token:d.token,created_at:d.created_at};state.boxes=state.boxes.filter(x=>x.box!==entry.box);state.boxes.unshift(entry);state.current=entry;state.messages=[];state.selected=null;state.full=null;save();$('quota').textContent=t('today',{used:d.used,limit:d.limit});status(entry.address,'ok');render();await loadMessages()}catch(e){status(e.message,'err')}}
function applyLang(lang){state.lang=I[lang]?lang:'en';localStorage.setItem(LS_LANG,state.lang);document.documentElement.lang=state.lang;document.documentElement.dir=state.lang==='ar'?'rtl':'ltr';render()}
function initLang(){for(const [code,name] of languages){const o=document.createElement('option');o.value=code;o.textContent=name;$('lang').appendChild(o)}const want=new URLSearchParams(location.search).get('lang')||localStorage.getItem(LS_LANG)||navigator.language||'en';const found=languages.find(([code])=>code.toLowerCase()===want.toLowerCase())||languages.find(([code])=>want.toLowerCase().startsWith(code.toLowerCase().split('-')[0]));$('lang').value=found?found[0]:'en';applyLang($('lang').value);$('lang').onchange=()=>applyLang($('lang').value)}
$('copy').onclick=async()=>{if($('addr').value){await navigator.clipboard.writeText($('addr').value);status(t('copied'),'ok')}};
$('create').onclick=createMailbox;$('refresh').onclick=loadMessages;
$('clear').onclick=async()=>{if(!state.current)return;await api('/api/clear',{method:'POST',body:JSON.stringify({box:state.current.box,token:state.current.token})});await loadMessages()};
$('delete').onclick=async()=>{if(!state.current||!state.selected)return;await api('/api/delete',{method:'POST',body:JSON.stringify({box:state.current.box,token:state.current.token,id:state.selected})});await loadMessages()};
(async()=>{state.fingerprint=await fp().catch(()=>'unavailable');load();initLang();render();if(state.current)loadMessages();setInterval(loadMessages,8000)})();
</script>
</body>
</html>""".replace("__DOMAIN__", DOMAIN)

FINAL_PUBLIC_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Temp Mail</title>
<meta name="description" content="Create a temporary mailbox and receive messages for 24 hours.">
<meta name="robots" content="index,follow">
<style>
:root{--bg:#f3f5f7;--surface:#ffffff;--line:#d8dee6;--ink:#16181d;--muted:#5d6673;--accent:#0f766e;--accent-soft:#ddf4f1;--danger:#b42318}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:linear-gradient(180deg,#f9fbfc 0,#f3f5f7 100%);color:var(--ink)}header{background:#fff;border-bottom:1px solid var(--line)}.wrap{width:min(1180px,calc(100% - 32px));margin:0 auto}.top{padding:20px 0;display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center}.tag{margin:8px 0 0;color:var(--muted);font-size:14px;line-height:1.5}.langbar{display:flex;gap:12px;align-items:center;justify-content:flex-end;flex-wrap:wrap}.pill{margin:0;color:var(--muted);font-size:13px}.hero{padding:22px 0 16px}.compose{display:grid;grid-template-columns:1.2fr 1fr auto auto auto;gap:10px;align-items:end}.field{display:grid;gap:6px}.field span{font-size:13px;color:var(--muted);font-weight:700}input,select,button{font:inherit}input,select{min-height:44px;border:1px solid var(--line);border-radius:10px;padding:0 12px;background:#fff;color:var(--ink)}button{min-height:44px;border:1px solid var(--ink);border-radius:10px;padding:0 14px;background:var(--ink);color:#fff;font-weight:700;cursor:pointer}button.secondary{background:#fff;color:var(--ink)}button.danger{background:#fff;color:var(--danger);border-color:var(--danger)}button:disabled{opacity:.55;cursor:not-allowed}.hint{margin:12px 0 0;color:var(--muted);font-size:13px}.status{margin:14px 0 0;font-size:14px;color:var(--muted)}.status.ok{color:var(--accent)}.status.err{color:var(--danger)}main{padding:10px 0 36px}.grid{display:grid;grid-template-columns:300px 340px 1fr;gap:16px}.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 10px 30px rgba(16,24,40,.04)}.head{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px;font-weight:700}.body{padding:16px}.list{min-height:520px;max-height:68vh;overflow:auto}.empty{padding:18px;color:var(--muted);line-height:1.5}.item{display:block;width:100%;border:0;border-bottom:1px solid var(--line);background:#fff;text-align:left;padding:14px 16px;cursor:pointer}.item:hover,.item.active{background:var(--accent-soft)}.title{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{margin-top:6px;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.reader{min-height:520px;max-height:68vh;overflow:auto}.reader h2{margin:0 0 10px;font-size:22px;line-height:1.3;word-break:break-word}.mailmeta{color:var(--muted);font-size:14px;line-height:1.6;margin-bottom:14px;word-break:break-word}.notice{margin-top:14px;color:var(--muted);font-size:13px;line-height:1.5}pre{margin:0;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;font-family:Consolas,Menlo,monospace;font-size:14px;line-height:1.55}a{color:#0b7285;text-decoration:none}a:hover{text-decoration:underline}[dir=rtl] .langbar{justify-content:flex-start}@media(max-width:980px){.compose{grid-template-columns:1fr 1fr}.compose .full{grid-column:1/-1}.grid{grid-template-columns:1fr}.list,.reader{max-height:none;min-height:260px}}@media(max-width:640px){.top{grid-template-columns:1fr}.compose{grid-template-columns:1fr}.wrap{width:min(100% - 24px,1180px)}}
</style>
</head>
<body>
<header>
  <div class="wrap top">
    <div>
      <h1 id="brand"></h1>
      <p class="tag" id="tagline"></p>
    </div>
    <div class="langbar">
      <p class="pill" id="quota"></p>
      <select id="lang" aria-label="Language"></select>
    </div>
  </div>
</header>
<section class="hero wrap">
  <div class="compose">
    <label class="field full"><span id="customLabel"></span><input id="customBox" autocomplete="off" spellcheck="false"></label>
    <div class="field"><span id="previewLabel"></span><input id="preview" readonly></div>
    <button id="createCustom"></button>
    <button class="secondary" id="createRandom"></button>
    <button class="secondary" id="copyAddress"></button>
  </div>
  <p class="hint" id="hint"></p>
  <div class="status" id="status"></div>
</section>
<main class="wrap">
  <div class="grid">
    <section class="panel">
      <div class="head"><span id="mailboxTitle"></span><button class="danger" id="clearMailbox"></button></div>
      <div class="list" id="mailboxList"></div>
    </section>
    <section class="panel">
      <div class="head"><span id="messageTitle"></span><button class="secondary" id="refreshMessages"></button></div>
      <div class="list" id="messageList"></div>
    </section>
    <section class="panel">
      <div class="head"><span id="readerTitle"></span><button class="danger" id="deleteMessage"></button></div>
      <div class="body reader" id="reader"></div>
    </section>
  </div>
</main>
<script>
const domain="__DOMAIN__";
const LS_BOXES="tm.boxes", LS_CURRENT="tm.current", LS_LANG="tm.lang";
const $ = id => document.getElementById(id);
const languages = [["zh-CN", "\u7b80\u4f53\u4e2d\u6587"], ["zh-TW", "\u7e41\u9ad4\u4e2d\u6587"], ["en", "English"], ["es", "Espanol"], ["de", "Deutsch"], ["fr", "Francais"], ["it", "Italiano"], ["pt", "Portugues"]];
const dict = {"zh-CN": {"brand": "\u4e34\u65f6\u90ae\u7bb1", "tagline": "\u7a33\u5b9a\u7248\u9996\u9875\uff0c\u652f\u6301\u591a\u8bed\u8a00\u5207\u6362\u3001\u81ea\u5b9a\u4e49\u90ae\u7bb1\u540d\u548c 24 \u5c0f\u65f6\u6536\u4fe1\u3002", "customLabel": "\u81ea\u5b9a\u4e49\u90ae\u7bb1\u524d\u7f00", "previewLabel": "\u5f53\u524d\u5730\u5740", "customPlaceholder": "\u4f8b\u5982\uff1anews, support, demo123", "createCustom": "\u521b\u5efa\u81ea\u5b9a\u4e49\u90ae\u7bb1", "createRandom": "\u968f\u673a\u521b\u5efa", "copy": "\u590d\u5236\u5730\u5740", "mailboxTitle": "\u6211\u7684\u90ae\u7bb1", "messageTitle": "\u90ae\u4ef6\u5217\u8868", "readerTitle": "\u90ae\u4ef6\u5185\u5bb9", "clear": "\u6e05\u7a7a\u90ae\u7bb1", "delete": "\u5220\u9664\u90ae\u4ef6", "refresh": "\u5237\u65b0", "hint": "\u89c4\u5219\uff1a\u53ea\u80fd\u4f7f\u7528\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u70b9\u3001\u4e0b\u5212\u7ebf\u3001\u52a0\u53f7\u548c\u51cf\u53f7\uff1b\u6700\u957f 64 \u4f4d\uff1b\u73b0\u5df2\u53d6\u6d88\u6bcf\u65e5\u521b\u5efa\u4e0a\u9650\u3002", "noMailbox": "\u8fd8\u6ca1\u6709\u90ae\u7bb1\uff0c\u8bf7\u5148\u521b\u5efa\u4e00\u4e2a\u3002", "noMessages": "\u5f53\u524d\u90ae\u7bb1\u8fd8\u6ca1\u6709\u90ae\u4ef6\u3002", "chooseMailbox": "\u8bf7\u5148\u4ece\u5de6\u4fa7\u9009\u62e9\u6216\u521b\u5efa\u90ae\u7bb1\u3002", "chooseMessage": "\u8bf7\u4ece\u4e2d\u95f4\u5217\u8868\u9009\u62e9\u4e00\u5c01\u90ae\u4ef6\u3002", "creating": "\u6b63\u5728\u521b\u5efa\u90ae\u7bb1...", "copied": "\u5730\u5740\u5df2\u590d\u5236\u3002", "from": "\u53d1\u4ef6\u4eba", "to": "\u6536\u4ef6\u4eba", "attachments": "\u9644\u4ef6", "todayLimited": "\u4eca\u65e5\u5df2\u521b\u5efa {used}/{limit}", "todayUnlimited": "\u4eca\u65e5\u5df2\u521b\u5efa {used}\uff08\u4e0d\u9650\u91cf\uff09", "loadFail": "\u64cd\u4f5c\u5931\u8d25\uff1a{error}", "invalidName": "\u8bf7\u8f93\u5165\u5408\u6cd5\u7684\u90ae\u7bb1\u524d\u7f00\u3002"}, "zh-TW": {"brand": "\u81e8\u6642\u4fe1\u7bb1", "tagline": "\u7a69\u5b9a\u7248\u9996\u9801\uff0c\u652f\u63f4\u591a\u8a9e\u5207\u63db\u3001\u81ea\u8a02\u4fe1\u7bb1\u540d\u7a31\u8207 24 \u5c0f\u6642\u6536\u4fe1\u3002", "customLabel": "\u81ea\u8a02\u4fe1\u7bb1\u524d\u7db4", "previewLabel": "\u76ee\u524d\u4f4d\u5740", "customPlaceholder": "\u4f8b\u5982\uff1anews, support, demo123", "createCustom": "\u5efa\u7acb\u81ea\u8a02\u4fe1\u7bb1", "createRandom": "\u96a8\u6a5f\u5efa\u7acb", "copy": "\u8907\u88fd\u4f4d\u5740", "mailboxTitle": "\u6211\u7684\u4fe1\u7bb1", "messageTitle": "\u90f5\u4ef6\u5217\u8868", "readerTitle": "\u90f5\u4ef6\u5167\u5bb9", "clear": "\u6e05\u7a7a\u4fe1\u7bb1", "delete": "\u522a\u9664\u90f5\u4ef6", "refresh": "\u91cd\u65b0\u6574\u7406", "hint": "\u898f\u5247\uff1a\u53ea\u80fd\u4f7f\u7528\u5b57\u6bcd\u3001\u6578\u5b57\u3001\u9ede\u3001\u5e95\u7dda\u3001\u52a0\u865f\u8207\u6e1b\u865f\uff1b\u6700\u9577 64 \u5b57\uff1b\u73fe\u5df2\u53d6\u6d88\u6bcf\u65e5\u5efa\u7acb\u4e0a\u9650\u3002", "noMailbox": "\u9084\u6c92\u6709\u4fe1\u7bb1\uff0c\u8acb\u5148\u5efa\u7acb\u4e00\u500b\u3002", "noMessages": "\u76ee\u524d\u4fe1\u7bb1\u9084\u6c92\u6709\u90f5\u4ef6\u3002", "chooseMailbox": "\u8acb\u5148\u5f9e\u5de6\u5074\u9078\u64c7\u6216\u5efa\u7acb\u4fe1\u7bb1\u3002", "chooseMessage": "\u8acb\u5f9e\u4e2d\u9593\u5217\u8868\u9078\u64c7\u4e00\u5c01\u90f5\u4ef6\u3002", "creating": "\u6b63\u5728\u5efa\u7acb\u4fe1\u7bb1...", "copied": "\u4f4d\u5740\u5df2\u8907\u88fd\u3002", "from": "\u5bc4\u4ef6\u8005", "to": "\u6536\u4ef6\u8005", "attachments": "\u9644\u4ef6", "todayLimited": "\u4eca\u65e5\u5df2\u5efa\u7acb {used}/{limit}", "todayUnlimited": "\u4eca\u65e5\u5df2\u5efa\u7acb {used}\uff08\u4e0d\u9650\u91cf\uff09", "loadFail": "\u64cd\u4f5c\u5931\u6557\uff1a{error}", "invalidName": "\u8acb\u8f38\u5165\u5408\u6cd5\u7684\u4fe1\u7bb1\u524d\u7db4\u3002"}, "en": {"brand": "Temp Mail", "tagline": "Stable homepage with more languages, custom mailbox names, and 24-hour inboxes.", "customLabel": "Custom mailbox prefix", "previewLabel": "Current address", "customPlaceholder": "Example: news, support, demo123", "createCustom": "Create custom mailbox", "createRandom": "Create random mailbox", "copy": "Copy address", "mailboxTitle": "My mailboxes", "messageTitle": "Messages", "readerTitle": "Message content", "clear": "Clear mailbox", "delete": "Delete message", "refresh": "Refresh", "hint": "Rules: letters, numbers, dot, underscore, plus and dash only; max length 64; daily mailbox creation limit is disabled.", "noMailbox": "No mailbox yet. Create one first.", "noMessages": "No messages in this mailbox yet.", "chooseMailbox": "Create or choose a mailbox from the left side first.", "chooseMessage": "Select a message from the middle list.", "creating": "Creating mailbox...", "copied": "Address copied.", "from": "From", "to": "To", "attachments": "Attachments", "todayLimited": "Created today {used}/{limit}", "todayUnlimited": "Created today {used} (unlimited)", "loadFail": "Action failed: {error}", "invalidName": "Please enter a valid mailbox prefix."}, "es": {"brand": "Correo temporal", "tagline": "Pagina estable con mas idiomas, nombres personalizados y bandeja de 24 horas.", "customLabel": "Prefijo del buzon", "previewLabel": "Direccion actual", "customPlaceholder": "Ejemplo: news, support, demo123", "createCustom": "Crear buzon personalizado", "createRandom": "Crear buzon aleatorio", "copy": "Copiar direccion", "mailboxTitle": "Mis buzones", "messageTitle": "Mensajes", "readerTitle": "Contenido del mensaje", "clear": "Vaciar buzon", "delete": "Eliminar mensaje", "refresh": "Actualizar", "hint": "Reglas: solo letras, numeros, punto, guion bajo, mas y guion; maximo 64 caracteres; el limite diario esta desactivado.", "noMailbox": "Todavia no hay buzon. Crea uno primero.", "noMessages": "Todavia no hay mensajes en este buzon.", "chooseMailbox": "Primero crea o elige un buzon.", "chooseMessage": "Selecciona un mensaje de la lista central.", "creating": "Creando buzon...", "copied": "Direccion copiada.", "from": "De", "to": "Para", "attachments": "Adjuntos", "todayLimited": "Creados hoy {used}/{limit}", "todayUnlimited": "Creados hoy {used} (sin limite)", "loadFail": "Accion fallida: {error}", "invalidName": "Introduce un prefijo valido."}, "de": {"brand": "Temp Mail", "tagline": "Stabile Startseite mit mehr Sprachen, eigenen Postfachnamen und Empfang fuer 24 Stunden.", "customLabel": "Postfach-Praefix", "previewLabel": "Aktuelle Adresse", "customPlaceholder": "Beispiel: news, support, demo123", "createCustom": "Eigenes Postfach erstellen", "createRandom": "Zufaelliges Postfach", "copy": "Adresse kopieren", "mailboxTitle": "Meine Postfaecher", "messageTitle": "Nachrichten", "readerTitle": "Nachrichteninhalt", "clear": "Postfach leeren", "delete": "Nachricht loeschen", "refresh": "Aktualisieren", "hint": "Regeln: Buchstaben, Zahlen, Punkt, Unterstrich, Plus und Bindestrich; maximal 64 Zeichen; das Tageslimit ist deaktiviert.", "noMailbox": "Noch kein Postfach. Bitte zuerst eines erstellen.", "noMessages": "In diesem Postfach gibt es noch keine Nachrichten.", "chooseMailbox": "Bitte zuerst links ein Postfach waehlen oder erstellen.", "chooseMessage": "Bitte eine Nachricht aus der mittleren Liste waehlen.", "creating": "Postfach wird erstellt...", "copied": "Adresse kopiert.", "from": "Von", "to": "An", "attachments": "Anhaenge", "todayLimited": "Heute erstellt {used}/{limit}", "todayUnlimited": "Heute erstellt {used} (unbegrenzt)", "loadFail": "Aktion fehlgeschlagen: {error}", "invalidName": "Bitte gib einen gueltigen Praefix ein."}, "fr": {"brand": "Email temporaire", "tagline": "Accueil stable avec plus de langues, noms personnalises et reception pendant 24 heures.", "customLabel": "Prefixe de boite", "previewLabel": "Adresse actuelle", "customPlaceholder": "Exemple: news, support, demo123", "createCustom": "Creer une boite personnalisee", "createRandom": "Creer une boite aleatoire", "copy": "Copier l'adresse", "mailboxTitle": "Mes boites", "messageTitle": "Messages", "readerTitle": "Contenu du message", "clear": "Vider la boite", "delete": "Supprimer le message", "refresh": "Actualiser", "hint": "Regles: lettres, chiffres, point, underscore, plus et tiret seulement; 64 caracteres max; la limite quotidienne est desactivee.", "noMailbox": "Aucune boite pour le moment. Creez-en une d'abord.", "noMessages": "Aucun message dans cette boite pour le moment.", "chooseMailbox": "Creez ou choisissez d'abord une boite a gauche.", "chooseMessage": "Selectionnez un message dans la liste du milieu.", "creating": "Creation de la boite...", "copied": "Adresse copiee.", "from": "De", "to": "A", "attachments": "Pieces jointes", "todayLimited": "Creees aujourd'hui {used}/{limit}", "todayUnlimited": "Creees aujourd'hui {used} (illimite)", "loadFail": "Action echouee: {error}", "invalidName": "Veuillez saisir un prefixe valide."}, "it": {"brand": "Email temporanea", "tagline": "Home stabile con piu lingue, nomi personalizzati e ricezione per 24 ore.", "customLabel": "Prefisso casella", "previewLabel": "Indirizzo attuale", "customPlaceholder": "Esempio: news, support, demo123", "createCustom": "Crea casella personalizzata", "createRandom": "Crea casella casuale", "copy": "Copia indirizzo", "mailboxTitle": "Le mie caselle", "messageTitle": "Messaggi", "readerTitle": "Contenuto messaggio", "clear": "Svuota casella", "delete": "Elimina messaggio", "refresh": "Aggiorna", "hint": "Regole: solo lettere, numeri, punto, underscore, piu e trattino; massimo 64 caratteri; il limite giornaliero e disattivato.", "noMailbox": "Nessuna casella ancora. Creane una prima.", "noMessages": "Non ci sono ancora messaggi in questa casella.", "chooseMailbox": "Crea o scegli prima una casella a sinistra.", "chooseMessage": "Seleziona un messaggio dalla lista centrale.", "creating": "Creazione casella...", "copied": "Indirizzo copiato.", "from": "Da", "to": "A", "attachments": "Allegati", "todayLimited": "Create oggi {used}/{limit}", "todayUnlimited": "Create oggi {used} (illimitato)", "loadFail": "Azione non riuscita: {error}", "invalidName": "Inserisci un prefisso valido."}, "pt": {"brand": "Email temporario", "tagline": "Pagina estavel com mais idiomas, nomes personalizados e caixa por 24 horas.", "customLabel": "Prefixo da caixa", "previewLabel": "Endereco atual", "customPlaceholder": "Exemplo: news, support, demo123", "createCustom": "Criar caixa personalizada", "createRandom": "Criar caixa aleatoria", "copy": "Copiar endereco", "mailboxTitle": "Minhas caixas", "messageTitle": "Mensagens", "readerTitle": "Conteudo da mensagem", "clear": "Limpar caixa", "delete": "Excluir mensagem", "refresh": "Atualizar", "hint": "Regras: apenas letras, numeros, ponto, underscore, mais e hifen; maximo 64 caracteres; o limite diario esta desativado.", "noMailbox": "Ainda nao ha caixa. Crie uma primeiro.", "noMessages": "Ainda nao ha mensagens nesta caixa.", "chooseMailbox": "Primeiro crie ou escolha uma caixa a esquerda.", "chooseMessage": "Selecione uma mensagem da lista do meio.", "creating": "Criando caixa...", "copied": "Endereco copiado.", "from": "De", "to": "Para", "attachments": "Anexos", "todayLimited": "Criadas hoje {used}/{limit}", "todayUnlimited": "Criadas hoje {used} (sem limite)", "loadFail": "Acao falhou: {error}", "invalidName": "Digite um prefixo valido."}};
const state = {boxes: [], current: null, messages: [], selected: null, currentMessage: null, fingerprint: "", lang: "zh-CN"};
function tr(key, vars={}) { let s = (dict[state.lang] && dict[state.lang][key]) || dict.en[key] || key; for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v)); return s; }
function cleanErr(value) { return String(value || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 500); }
function normalizeLocal(value) { return String(value || "").trim().toLowerCase().replace(/@.*$/, "").replace(/[^a-z0-9._+-]/g, "").slice(0, 64); }
async function api(url, opt={}) { opt.credentials = "include"; opt.headers = Object.assign({"Content-Type": "application/json"}, opt.headers || {}); const resp = await fetch(url, opt); const txt = await resp.text(); let data = {}; try { data = txt ? JSON.parse(txt) : {}; } catch (err) { data = {error: cleanErr(txt)}; } if (!resp.ok) throw new Error(cleanErr(data.error) || resp.statusText); return data; }
async function makeFingerprint() { const raw = [navigator.userAgent, navigator.language, screen.width + "x" + screen.height, Intl.DateTimeFormat().resolvedOptions().timeZone, navigator.platform, navigator.hardwareConcurrency || ""].join("|"); const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)); return Array.from(new Uint8Array(buf)).map(x => x.toString(16).padStart(2, "0")).join(""); }
function save() { localStorage.setItem(LS_BOXES, JSON.stringify(state.boxes)); localStorage.setItem(LS_CURRENT, state.current ? state.current.box : ""); }
function load() { try { state.boxes = JSON.parse(localStorage.getItem(LS_BOXES) || "[]"); } catch (err) { state.boxes = []; } const current = localStorage.getItem(LS_CURRENT) || ""; state.current = state.boxes.find(x => x.box === current) || state.boxes[0] || null; }
function setStatus(message, kind="") { const el = $("status"); el.textContent = message || ""; el.className = "status" + (kind ? " " + kind : ""); }
function syncPreview() { const local = normalizeLocal($("customBox").value); $("preview").value = local ? `${local}@${domain}` : (state.current ? state.current.address : `@${domain}`); }
function renderChrome() { document.documentElement.lang = state.lang; document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr"; document.title = tr("brand") + " - Temp Mail"; $("brand").textContent = tr("brand"); $("tagline").textContent = tr("tagline"); $("customLabel").textContent = tr("customLabel"); $("previewLabel").textContent = tr("previewLabel"); $("customBox").placeholder = tr("customPlaceholder"); $("createCustom").textContent = tr("createCustom"); $("createRandom").textContent = tr("createRandom"); $("copyAddress").textContent = tr("copy"); $("mailboxTitle").textContent = tr("mailboxTitle"); $("messageTitle").textContent = tr("messageTitle"); $("readerTitle").textContent = tr("readerTitle"); $("clearMailbox").textContent = tr("clear"); $("deleteMessage").textContent = tr("delete"); $("refreshMessages").textContent = tr("refresh"); $("hint").textContent = tr("hint"); }
function renderMailboxes() { const list = $("mailboxList"); list.innerHTML = ""; if (!state.boxes.length) { list.innerHTML = `<div class="empty">${tr("noMailbox")}</div>`; return; } for (const box of state.boxes) { const btn = document.createElement("button"); btn.className = "item" + (state.current && state.current.box === box.box ? " active" : ""); btn.innerHTML = '<div class="title"></div><div class="meta"></div>'; btn.querySelector(".title").textContent = box.address; btn.querySelector(".meta").textContent = box.created_at || ""; btn.onclick = () => { state.current = box; state.selected = null; state.currentMessage = null; save(); render(); loadMessages(); }; list.appendChild(btn); } }
function renderMessages() { const list = $("messageList"); list.innerHTML = ""; if (!state.current) { list.innerHTML = `<div class="empty">${tr("chooseMailbox")}</div>`; return; } if (!state.messages.length) { list.innerHTML = `<div class="empty">${tr("noMessages")}</div>`; return; } for (const m of state.messages) { const btn = document.createElement("button"); btn.className = "item" + (m.id === state.selected ? " active" : ""); btn.innerHTML = '<div class="title"></div><div class="meta"></div><div class="meta"></div>'; btn.querySelector(".title").textContent = m.subject || "(no subject)"; const meta = btn.querySelectorAll(".meta"); meta[0].textContent = m.sender || "unknown"; meta[1].textContent = m.received_at || ""; btn.onclick = () => openMessage(m.id); list.appendChild(btn); } }
function renderReader() { const reader = $("reader"); $("clearMailbox").disabled = !state.current; $("deleteMessage").disabled = !state.selected; if (!state.current) { reader.innerHTML = `<div class="empty">${tr("chooseMailbox")}</div>`; return; } if (!state.currentMessage) { reader.innerHTML = `<div class="empty">${state.messages.length ? tr("chooseMessage") : tr("noMessages")}</div>`; return; } const m = state.currentMessage; reader.innerHTML = ""; const h = document.createElement("h2"); h.textContent = m.subject || "(no subject)"; const meta = document.createElement("div"); meta.className = "mailmeta"; meta.textContent = `${tr("from")}: ${m.sender || "unknown"}  ${tr("to")}: ${m.recipient || ""}  ${m.received_at || ""}`; const pre = document.createElement("pre"); pre.textContent = m.text || m.raw || ""; reader.append(h, meta, pre); if (m.attachments && m.attachments.length) { const wrap = document.createElement("div"); wrap.className = "notice"; wrap.textContent = tr("attachments") + ": "; for (const a of m.attachments) { const link = document.createElement("a"); link.href = `/api/attachment?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}&id=${a.id}`; link.textContent = `${a.filename} (${Math.ceil(a.size / 1024)} KB)`; link.style.marginRight = "12px"; wrap.appendChild(link); } reader.appendChild(wrap); } }
function render() { renderChrome(); renderMailboxes(); renderMessages(); renderReader(); syncPreview(); }
async function loadMessages() { if (!state.current) { render(); return; } try { const data = await api(`/api/messages?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}`, {headers: {}}); state.messages = data.messages || []; state.selected = null; state.currentMessage = null; render(); setStatus(""); } catch (err) { state.messages = []; state.selected = null; state.currentMessage = null; render(); setStatus(tr("loadFail", {error: err.message}), "err"); } }
async function openMessage(id) { state.selected = id; state.currentMessage = null; render(); try { state.currentMessage = await api(`/api/message?box=${encodeURIComponent(state.current.box)}&token=${encodeURIComponent(state.current.token)}&id=${id}`, {headers: {}}); render(); } catch (err) { setStatus(tr("loadFail", {error: err.message}), "err"); } }
async function createMailbox(custom) { try { const local = normalizeLocal($("customBox").value); if (custom && !local) { setStatus(tr("invalidName"), "err"); return; } setStatus(tr("creating")); const body = {fingerprint: state.fingerprint}; if (custom) body.box = local; const data = await api("/api/create-mailbox", {method: "POST", body: JSON.stringify(body)}); const entry = {box: data.box, address: data.address, token: data.token, created_at: data.created_at}; state.boxes = state.boxes.filter(x => x.box !== entry.box); state.boxes.unshift(entry); state.current = entry; state.messages = []; state.selected = null; state.currentMessage = null; save(); $("quota").textContent = (data.limit == null) ? tr("todayUnlimited", {used: data.used}) : tr("todayLimited", {used: data.used, limit: data.limit}); $("customBox").value = entry.box; render(); setStatus(entry.address, "ok"); await loadMessages(); } catch (err) { setStatus(tr("loadFail", {error: err.message}), "err"); } }
async function copyAddress() { const value = state.current ? state.current.address : $("preview").value; if (value) { await navigator.clipboard.writeText(value); setStatus(tr("copied"), "ok"); } }
function initLang() { for (const [code, name] of languages) { const opt = document.createElement("option"); opt.value = code; opt.textContent = name; $("lang").appendChild(opt); } const wanted = new URLSearchParams(location.search).get("lang") || localStorage.getItem(LS_LANG) || navigator.language || "zh-CN"; const found = languages.find(([code]) => code.toLowerCase() === wanted.toLowerCase()) || languages.find(([code]) => wanted.toLowerCase().startsWith(code.toLowerCase().split("-")[0])); $("lang").value = found ? found[0] : "zh-CN"; state.lang = $("lang").value; $("lang").onchange = () => { state.lang = $("lang").value; localStorage.setItem(LS_LANG, state.lang); render(); }; }
$("customBox").addEventListener("input", syncPreview);
$("createCustom").onclick = () => createMailbox(true);
$("createRandom").onclick = () => createMailbox(false);
$("copyAddress").onclick = copyAddress;
$("refreshMessages").onclick = loadMessages;
$("clearMailbox").onclick = async () => { if (!state.current) return; await api("/api/clear", {method: "POST", body: JSON.stringify({box: state.current.box, token: state.current.token})}); await loadMessages(); };
$("deleteMessage").onclick = async () => { if (!state.current || !state.selected) return; await api("/api/delete", {method: "POST", body: JSON.stringify({box: state.current.box, token: state.current.token, id: state.selected})}); await loadMessages(); };
(async () => { state.fingerprint = await makeFingerprint().catch(() => "unavailable"); load(); initLang(); render(); if (state.current) await loadMessages(); setInterval(loadMessages, 8000); })();
</script>
</body>
</html>""".replace("__DOMAIN__", DOMAIN)


class HtmlText:
    def __init__(self):
        from html.parser import HTMLParser
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__(); self.parts=[]
            def handle_data(self, data):
                self.parts.append(data)
            def handle_starttag(self, tag, attrs):
                if tag in ("br","p","div","tr"):
                    self.parts.append("\n")
        self.parser_class=Parser
    def strip(self, value):
        parser=self.parser_class(); parser.feed(value or "")
        return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
HTML_STRIPPER=HtmlText()

def now_dt(): return datetime.now(timezone.utc)
def now_iso(): return now_dt().replace(microsecond=0).isoformat()
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn=sqlite3.connect(DB_PATH, timeout=30); conn.row_factory=sqlite3.Row; return conn

def hash_password(password, salt_hex=None):
    if salt_hex is None: salt_hex=os.urandom(16).hex()
    digest=hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PASSWORD_ITERATIONS).hex()
    return salt_hex, digest

def verify_password(password, salt_hex, stored_hash):
    return hmac.compare_digest(hash_password(password, salt_hex)[1], stored_hash or "")

def admin_bootstrap_values():
    if ADMIN_PASSWORD:
        salt, password_hash = hash_password(ADMIN_PASSWORD, ADMIN_SALT or None)
        return ADMIN_USERNAME, ADMIN_EMAIL, salt, password_hash
    if ADMIN_SALT and ADMIN_PASSWORD_HASH:
        return ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_SALT, ADMIN_PASSWORD_HASH
    return None

def init_db():
    with DB_LOCK, db() as conn:
        conn.execute("pragma journal_mode=wal")
        conn.execute("""create table if not exists messages(id integer primary key autoincrement,mailbox text not null,recipient text not null,sender text,subject text,received_at text not null,expires_at text not null,raw text not null,text text not null)""")
        conn.execute("create index if not exists idx_messages_mailbox on messages(mailbox, received_at desc)")
        conn.execute("create index if not exists idx_messages_expires on messages(expires_at)")
        conn.execute("""create table if not exists attachments(id integer primary key autoincrement,message_id integer not null,filename text not null,content_type text not null,size integer not null,data blob not null,created_at text not null)""")
        conn.execute("create index if not exists idx_attachments_message on attachments(message_id)")
        conn.execute("""create table if not exists archived_messages(id integer primary key autoincrement,original_message_id integer,mailbox text not null,recipient text not null,sender text,subject text,received_at text not null,archived_at text not null,raw text not null,text text not null)""")
        conn.execute("create index if not exists idx_archived_mailbox on archived_messages(mailbox, received_at desc)")
        conn.execute("""create table if not exists archived_attachments(id integer primary key autoincrement,archived_message_id integer not null,filename text not null,content_type text not null,size integer not null,data blob not null,created_at text not null)""")
        conn.execute("create index if not exists idx_archived_attachments_message on archived_attachments(archived_message_id)")
        conn.execute("""create table if not exists email_codes(email text primary key,code_hash text not null,salt text not null,created_at text not null,expires_at text not null,used_at text,attempts integer not null default 0)""")
        conn.execute("""create table if not exists archive_runs(local_date text primary key,ran_at text not null)""")
        conn.execute("""create table if not exists users(id integer primary key autoincrement,username text not null unique,email text not null unique,password_hash text not null,salt text not null,role text not null default 'user',created_at text not null)""")
        conn.execute("create index if not exists idx_users_email on users(email)")
        conn.execute("""create table if not exists sessions(token text primary key,user_id integer not null,created_at text not null,expires_at text not null,foreign key(user_id) references users(id) on delete cascade)""")
        conn.execute("create index if not exists idx_sessions_user on sessions(user_id)")
        conn.execute("create index if not exists idx_sessions_expires on sessions(expires_at)")
        conn.execute("""create table if not exists sent_messages(id integer primary key autoincrement,user_id integer not null,sender text not null,recipient text not null,subject text,sent_at text not null,status text not null,error text,foreign key(user_id) references users(id) on delete cascade)""")
        conn.execute("create index if not exists idx_sent_user_time on sent_messages(user_id, sent_at)")
        conn.execute("create index if not exists idx_sent_time on sent_messages(sent_at)")
        conn.execute("""create table if not exists mailbox_creations(id integer primary key autoincrement,mailbox text not null unique,token text not null,created_at text not null,local_date text not null,ip text,fingerprint text,fingerprint_hash text,identity_key text,user_agent text,created_by text not null default 'guest')""")
        conn.execute("create index if not exists idx_mailbox_creations_day_identity on mailbox_creations(local_date, identity_key)")
        conn.execute("create index if not exists idx_mailbox_creations_day_fingerprint on mailbox_creations(local_date, fingerprint_hash)")
        conn.execute("create index if not exists idx_mailbox_creations_mailbox on mailbox_creations(mailbox)")
        bootstrap_admin(conn); conn.commit()

def bootstrap_admin(conn):
    admin = admin_bootstrap_values()
    if not admin:
        print("admin bootstrap skipped: set TEMPMAIL_ADMIN_PASSWORD or TEMPMAIL_ADMIN_PASSWORD_HASH with TEMPMAIL_ADMIN_SALT", flush=True)
        return
    username, email, salt, password_hash = admin
    row=conn.execute("select id from users where lower(username)=lower(?)", (username,)).fetchone()
    if row:
        conn.execute("update users set email=?, password_hash=?, salt=?, role=? where id=?", (email, password_hash, salt, "admin", row["id"]))
    else:
        conn.execute("insert into users(username,email,password_hash,salt,role,created_at) values(?,?,?,?,?,?)", (username, email, password_hash, salt, "admin", now_iso()))
def purge_old():
    cutoff=now_iso()
    mailbox_cutoff=(now_dt()-timedelta(hours=TTL_HOURS)).replace(microsecond=0).isoformat()
    with DB_LOCK, db() as conn:
        conn.execute("delete from attachments where message_id in (select id from messages where expires_at <= ?)", (cutoff,))
        conn.execute("delete from messages where expires_at <= ?", (cutoff,))
        conn.execute("delete from sessions where expires_at <= ?", (cutoff,))
        conn.execute("delete from email_codes where expires_at <= ? or used_at is not null", (cutoff,))
        stale_boxes=conn.execute("select mailbox from mailbox_creations where created_by='guest' and created_at <= ?", (mailbox_cutoff,)).fetchall()
        for row in stale_boxes:
            if not conn.execute("select 1 from messages where mailbox=? and expires_at > ? limit 1", (row["mailbox"], cutoff)).fetchone():
                conn.execute("delete from mailbox_creations where mailbox=? and created_by='guest'", (row["mailbox"],))
        conn.commit()

def normalize_box(value):
    addr=parseaddr(value or "")[1] or (value or "")
    local=addr.split("@",1)[0].strip().lower()
    if not BOX_RE.match(local): raise ValueError("Invalid mailbox name")
    return local

def normalize_recipient_box(value):
    addr=parseaddr(value or "")[1] or (value or "")
    addr=addr.strip().lower()
    if "@" in addr:
        local, domain=addr.rsplit("@",1)
        if domain.rstrip(".") != DOMAIN: raise ValueError("Invalid recipient domain")
    else:
        local=addr
    if not BOX_RE.match(local): raise ValueError("Invalid mailbox name")
    return local

def is_valid_email(value):
    if not value or len(value)>320 or "@" not in value: return False
    local, domain=value.rsplit("@",1)
    if not local or not domain or len(local)>64 or len(domain)>253: return False
    if any(ch.isspace() for ch in value) or "<" in value or ">" in value: return False
    try: domain.encode("idna").decode("ascii")
    except Exception: return False
    return "." in domain or domain == DOMAIN

def normalize_login_email(value):
    addr=parseaddr(value or "")[1] or (value or "")
    addr=addr.strip().lower()
    if not is_valid_email(addr): raise ValueError("Invalid email")
    return addr

def normalize_outbound_email(value):
    addr=parseaddr(value or "")[1] or (value or "")
    addr=addr.strip()
    if not is_valid_email(addr.lower()): raise ValueError("Invalid email address")
    local, domain=addr.rsplit("@",1)
    return f"{local}@{domain.encode('idna').decode('ascii').lower()}"

def make_random_box():
    alphabet=string.ascii_lowercase+string.digits
    return "box"+"".join(secrets.choice(alphabet) for _ in range(16))

def today_utc8():
    return now_dt().astimezone(UTC8).date().isoformat()

def hash_text(value):
    return hashlib.sha256((value or "").encode("utf-8", "replace")).hexdigest()

def client_ip(handler):
    for header in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
        value=(handler.headers.get(header, "") or "").strip()
        if value:
            first=value.split(",", 1)[0].strip()
            if first: return first[:80]
    try: return (handler.client_address[0] or "")[:80]
    except Exception: return ""

def clean_fingerprint(value):
    value=re.sub(r"\s+", " ", str(value or "")).strip()
    return (value or "unknown")[:512]

def identity_for(ip, fingerprint):
    return hash_text(f"{ip}|{fingerprint}")

def mailbox_creation_count(conn, local_date, identity_key, fingerprint_hash):
    unknown=hash_text("unknown")
    if fingerprint_hash and fingerprint_hash != unknown:
        row=conn.execute("""select count(*) as c from mailbox_creations where local_date=? and created_by='guest' and (identity_key=? or fingerprint_hash=?)""", (local_date, identity_key, fingerprint_hash)).fetchone()
    else:
        row=conn.execute("""select count(*) as c from mailbox_creations where local_date=? and created_by='guest' and identity_key=?""", (local_date, identity_key)).fetchone()
    return int(row["c"] if row else 0)

def release_expired_guest_mailbox(conn, mailbox, now_text=None):
    now_text=now_text or now_iso()
    mailbox_cutoff=(datetime.fromisoformat(now_text)-timedelta(hours=TTL_HOURS)).replace(microsecond=0).isoformat()
    row=conn.execute("select created_at,created_by from mailbox_creations where mailbox=?", (mailbox,)).fetchone()
    if not row or row["created_by"] != "guest" or row["created_at"] > mailbox_cutoff:
        return False
    if conn.execute("select 1 from messages where mailbox=? and expires_at > ? limit 1", (mailbox, now_text)).fetchone():
        return False
    conn.execute("delete from mailbox_creations where mailbox=? and created_by='guest'", (mailbox,))
    return True

def create_guest_mailbox(ip, fingerprint, user_agent, requested_box=""):
    fingerprint=clean_fingerprint(fingerprint); fingerprint_hash=hash_text(fingerprint); identity_key=identity_for(ip, fingerprint)
    user_agent=(user_agent or "")[:500]; local_date=today_utc8(); created=now_iso()
    requested_box=(requested_box or "").strip(); limit=(MAILBOX_DAILY_LIMIT if MAILBOX_DAILY_LIMIT > 0 else None)
    with DB_LOCK, db() as conn:
        used=mailbox_creation_count(conn, local_date, identity_key, fingerprint_hash)
        if limit is not None and used >= limit: raise RuntimeError("daily mailbox creation limit reached")
        if requested_box:
            mailbox=normalize_recipient_box(requested_box); token=secrets.token_urlsafe(24)
            release_expired_guest_mailbox(conn, mailbox, created)
            try:
                conn.execute("""insert into mailbox_creations(mailbox,token,created_at,local_date,ip,fingerprint,fingerprint_hash,identity_key,user_agent,created_by) values(?,?,?,?,?,?,?,?,?,?)""", (mailbox,token,created,local_date,ip,fingerprint,fingerprint_hash,identity_key,user_agent,"guest"))
                conn.commit(); return {"box":mailbox,"address":f"{mailbox}@{DOMAIN}","token":token,"created_at":created,"used":used+1,"limit":limit}
            except sqlite3.IntegrityError:
                raise RuntimeError("mailbox already exists")
        for _ in range(40):
            mailbox=make_random_box(); token=secrets.token_urlsafe(24)
            try:
                conn.execute("""insert into mailbox_creations(mailbox,token,created_at,local_date,ip,fingerprint,fingerprint_hash,identity_key,user_agent,created_by) values(?,?,?,?,?,?,?,?,?,?)""", (mailbox,token,created,local_date,ip,fingerprint,fingerprint_hash,identity_key,user_agent,"guest"))
                conn.commit(); return {"box":mailbox,"address":f"{mailbox}@{DOMAIN}","token":token,"created_at":created,"used":used+1,"limit":limit}
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("could not create mailbox")

def ensure_admin_mailbox(local, handler=None):
    mailbox=normalize_box(local); ip=client_ip(handler) if handler else "admin"
    created=now_iso(); local_date=today_utc8(); token=secrets.token_urlsafe(24)
    ua=(handler.headers.get("User-Agent","")[:500] if handler else "")
    with DB_LOCK, db() as conn:
        if not conn.execute("select 1 from mailbox_creations where mailbox=?", (mailbox,)).fetchone():
            conn.execute("""insert into mailbox_creations(mailbox,token,created_at,local_date,ip,fingerprint,fingerprint_hash,identity_key,user_agent,created_by) values(?,?,?,?,?,?,?,?,?,?)""", (mailbox,token,created,local_date,ip,"admin",hash_text("admin"),f"admin:{mailbox}",ua,"admin"))
            conn.commit()
    return mailbox

def is_known_mailbox(local):
    with DB_LOCK, db() as conn:
        if release_expired_guest_mailbox(conn, local):
            conn.commit()
        return conn.execute("select 1 from mailbox_creations where mailbox=?", (local,)).fetchone() is not None

def mailbox_access_ok(local, token):
    if not token: return False
    with DB_LOCK, db() as conn:
        if release_expired_guest_mailbox(conn, local):
            conn.commit()
        return conn.execute("select 1 from mailbox_creations where mailbox=? and token=?", (local, token)).fetchone() is not None

def normalize_admin_sender(value):
    raw=(parseaddr(value or "")[1] or (value or "")).strip().lower()
    if not raw: raise ValueError("sender is required")
    if "@" in raw:
        local, domain=raw.rsplit("@", 1)
        if domain.rstrip(".") != DOMAIN: raise ValueError("sender domain must be " + DOMAIN)
    else:
        local=raw
    if not BOX_RE.match(local): raise ValueError("invalid sender mailbox name")
    return local


def safe_filename(value, content_type="application/octet-stream"):
    name=os.path.basename((value or "").replace("\\", "/")).strip().strip(".")
    if not name:
        ext={ "image/jpeg":".jpg", "image/png":".png", "application/pdf":".pdf", "image/webp":".webp", "image/gif":".gif", "text/plain":".txt" }.get(content_type, ".txt")
        name="attachment"+ext
    name=re.sub(r"[^A-Za-z0-9._+-]", "_", name)[:160]
    if "." not in name:
        name += ".txt"
    return name

def extract_attachments(msg):
    if msg is None:
        return []
    attachments=[]; total=0
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        disp=(part.get_content_disposition() or "").lower()
        filename=part.get_filename()
        if disp!="attachment" and not filename:
            continue
        ctype=part.get_content_type()
        filename=safe_filename(filename, ctype)
        ext=os.path.splitext(filename.lower())[1]
        if ext not in ALLOWED_ATTACHMENT_EXTS:
            raise ValueError("unsupported attachment type")
        data=part.get_payload(decode=True) or b""
        size=len(data); total += size
        if size > MAX_ATTACHMENT_BYTES or total > MAX_ATTACHMENT_TOTAL_BYTES:
            raise ValueError("attachment too large")
        attachments.append({"filename":filename,"content_type":ctype or "application/octet-stream","size":size,"data":data})
    return attachments

def registration_domain_allowed(email):
    try:
        domain=email.rsplit("@",1)[1].lower()
    except Exception:
        return False
    return domain in ALLOWED_REGISTRATION_DOMAINS

def make_code():
    return f"{secrets.randbelow(1000000):06d}"

def store_email_code(email, code):
    salt,digest=hash_password(code)
    created=now_iso(); expires=(now_dt()+timedelta(minutes=CODE_TTL_MINUTES)).replace(microsecond=0).isoformat()
    with DB_LOCK, db() as conn:
        conn.execute("insert or replace into email_codes(email,code_hash,salt,created_at,expires_at,used_at,attempts) values(?,?,?,?,?,?,0)", (email,digest,salt,created,expires,None))
        conn.commit()

def code_recently_sent(email):
    with DB_LOCK, db() as conn:
        row=conn.execute("select created_at from email_codes where email=? and used_at is null", (email,)).fetchone()
    if not row:
        return False
    try:
        created=datetime.fromisoformat(row["created_at"])
        return (now_dt()-created).total_seconds() < CODE_RESEND_SECONDS
    except Exception:
        return False

def verify_email_code(email, code):
    with DB_LOCK, db() as conn:
        row=conn.execute("select * from email_codes where email=? and used_at is null and expires_at>?", (email, now_iso())).fetchone()
        if not row:
            return False
        attempts=int(row["attempts"] or 0)+1
        conn.execute("update email_codes set attempts=? where email=?", (attempts,email))
        conn.commit()
    if attempts > 8:
        return False
    ok=verify_password((code or "").strip(), row["salt"], row["code_hash"])
    if ok:
        with DB_LOCK, db() as conn:
            conn.execute("update email_codes set used_at=? where email=?", (now_iso(), email))
            conn.commit()
    return ok

def archive_due_messages():
    cutoff_local=datetime.combine(now_dt().astimezone(UTC8).date(), datetime.min.time(), tzinfo=UTC8)
    cutoff_utc=cutoff_local.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    archived_at=now_iso(); local_date=cutoff_local.date().isoformat()
    with DB_LOCK, db() as conn:
        rows=conn.execute("select * from messages where received_at < ? order by id", (cutoff_utc,)).fetchall()
        for row in rows:
            cur=conn.execute("insert into archived_messages(original_message_id,mailbox,recipient,sender,subject,received_at,archived_at,raw,text) values(?,?,?,?,?,?,?,?,?)", (row["id"],row["mailbox"],row["recipient"],row["sender"],row["subject"],row["received_at"],archived_at,row["raw"],row["text"]))
            archive_id=cur.lastrowid
            atts=conn.execute("select * from attachments where message_id=?", (row["id"],)).fetchall()
            for att in atts:
                conn.execute("insert into archived_attachments(archived_message_id,filename,content_type,size,data,created_at) values(?,?,?,?,?,?)", (archive_id,att["filename"],att["content_type"],att["size"],att["data"],archived_at))
            conn.execute("delete from attachments where message_id=?", (row["id"],))
            conn.execute("delete from messages where id=?", (row["id"],))
        conn.execute("insert or replace into archive_runs(local_date,ran_at) values(?,?)", (local_date, archived_at))
        conn.commit()
    if rows:
        print(f"archived {len(rows)} messages before {cutoff_utc}", flush=True)

def archive_loop():
    while True:
        try:
            archive_due_messages()
        except Exception as exc:
            print(f"archive error: {exc}", file=sys.stderr, flush=True)
        time.sleep(60)

def extract_text(msg):
    plain=None; fallback=None
    if msg.is_multipart():
        for part in msg.walk():
            ctype=part.get_content_type(); disp=(part.get("content-disposition") or "").lower()
            if "attachment" in disp: continue
            try: content=part.get_content()
            except Exception: continue
            if ctype=="text/plain" and plain is None: plain=content
            elif ctype=="text/html" and fallback is None: fallback=HTML_STRIPPER.strip(content)
    else:
        try: content=msg.get_content()
        except Exception:
            payload=msg.get_payload(decode=True) or b""; content=payload.decode("utf-8","replace")
        if msg.get_content_type()=="text/html": fallback=HTML_STRIPPER.strip(content)
        else: plain=content
    return str(plain if plain is not None else (fallback or ""))[:MAX_TEXT_CHARS]

def store_message(peer, mailfrom, rcpttos, data):
    if len(data)>MAX_MESSAGE_BYTES: return "552 message too large"
    received=now_iso(); expires=(now_dt()+timedelta(hours=TTL_HOURS)).replace(microsecond=0).isoformat()
    try: msg=BytesParser(policy=policy.default).parsebytes(data)
    except Exception: msg=None
    subject=""; text=""; sender=parseaddr(mailfrom or "")[1] or (mailfrom or "")
    if msg is not None:
        subject=str(msg.get("subject", ""))[:500]
        sender=parseaddr(msg.get("from", "") or mailfrom or "")[1] or sender
        text=extract_text(msg)
    try:
        attachments=extract_attachments(msg)
    except ValueError as exc:
        if "large" in str(exc):
            return "552 attachment too large"
        return "550 unsupported attachment type"
    raw=data.decode("utf-8","replace")[:MAX_TEXT_CHARS]
    rows=[]
    for recipient in rcpttos or []:
        try: mailbox=normalize_recipient_box(recipient)
        except ValueError: continue
        if not is_known_mailbox(mailbox):
            continue
        addr=parseaddr(recipient)[1] or recipient
        rows.append((mailbox, addr[:320], sender[:320], subject, received, expires, raw, text))
    if not rows: return "550 no valid recipient"
    purge_old()
    with DB_LOCK, db() as conn:
        for row in rows:
            cur=conn.execute("insert into messages(mailbox,recipient,sender,subject,received_at,expires_at,raw,text) values(?,?,?,?,?,?,?,?)", row)
            message_id=cur.lastrowid
            for att in attachments:
                conn.execute("insert into attachments(message_id,filename,content_type,size,data,created_at) values(?,?,?,?,?,?)", (message_id,att["filename"],att["content_type"],att["size"],att["data"],received))
        conn.commit()
    print(f"stored {len(rows)} message copy from {sender} with {len(attachments)} attachments", flush=True)
    return None

def create_session(user_id):
    token=secrets.token_urlsafe(32); created=now_iso(); expires=(now_dt()+timedelta(days=SESSION_DAYS)).replace(microsecond=0).isoformat()
    with DB_LOCK, db() as conn:
        conn.execute("insert into sessions(token,user_id,created_at,expires_at) values(?,?,?,?)", (token,user_id,created,expires)); conn.commit()
    return token

def sent_count_today(user_id):
    start=now_dt().date().isoformat()+"T00:00:00+00:00"
    with DB_LOCK, db() as conn:
        row=conn.execute("select count(*) as c from sent_messages where user_id=? and sent_at>=?", (user_id,start)).fetchone()
    return int(row["c"] if row else 0)

def user_payload(row):
    if not row: return None
    return {"id":row["id"],"username":row["username"],"email":row["email"],"role":row["role"],"created_at":row["created_at"],"sent_today":sent_count_today(row["id"]),"daily_limit":None if row["role"]=="admin" else DAILY_SEND_LIMIT}

def resolve_mx(domain):
    hosts=[]
    try:
        proc=subprocess.run(["dig","+short","MX",domain], capture_output=True, text=True, timeout=10)
        entries=[]
        for line in proc.stdout.splitlines():
            parts=line.strip().split()
            if len(parts)>=2 and parts[0].isdigit(): entries.append((int(parts[0]), parts[1].rstrip(".")))
        hosts=[host for _,host in sorted(entries)]
    except Exception:
        hosts=[]
    return (hosts or [domain])[:5]

def deliver_email(sender, recipient, subject, body, display_name):
    recipient=normalize_outbound_email(recipient); recipient_domain=recipient.rsplit("@",1)[1]
    msg=EmailMessage(); msg["From"]=formataddr((display_name, sender)); msg["To"]=recipient; msg["主题"]=subject[:200]
    msg["Date"]=formatdate(localtime=True); msg["Message-ID"]=make_msgid(domain=DOMAIN); msg["X-Mailer"]=f"{DOMAIN} Temp Mail"; msg.set_content(body[:20000] or " ")
    errors=[]
    for mx in resolve_mx(recipient_domain):
        try:
            with smtplib.SMTP(mx, 25, timeout=25) as smtp:
                smtp.ehlo_or_helo_if_needed(); smtp.send_message(msg, from_addr=sender, to_addrs=[recipient])
            return {"ok":True,"mx":mx,"recipient":recipient}
        except Exception as exc:
            errors.append(f"{mx}: {exc}")
    raise RuntimeError("; ".join(errors) or "delivery failed")

def spf_blocks_outbound():
    try:
        proc=subprocess.run(["dig","+short","TXT",DOMAIN], capture_output=True, text=True, timeout=8)
        text=" ".join(proc.stdout.replace('"',"").split()).lower()
    except Exception:
        return False
    if "v=spf1" not in text:
        return False
    return "-all" in text and "ip4:192.227.228.86" not in text and " mx " not in f" {text} " and " a " not in f" {text} "

def friendly_delivery_error(exc):
    text=html.unescape(str(exc) or "")
    text=re.sub(r"(?is)<script.*?</script>", " ", text)
    text=re.sub(r"(?is)<style.*?</style>", " ", text)
    text=re.sub(r"(?s)<[^>]+>", " ", text)
    text=re.sub(r"\s+", " ", text).strip()
    low=text.lower()
    if "bad gateway" in low or "cloudflare" in low:
        return "验证码邮件发送失败：上游返回 502。请先确认 Cloudflare DNS 的 SPF 已改为 v=spf1 ip4:192.227.228.86 -all，然后重试。"
    if "nosuchuser" in low or "mailbox not found" in low or "does not exist" in low:
        return "验证码邮件发送失败：目标邮箱不存在或被收件方拒收，请检查邮箱地址。"
    if "spf" in low or "dmarc" in low or "5.7.26" in low or "unauthenticated" in low:
        return "验证码邮件发送失败：emali.net 邮件认证未通过。请配置 SPF：v=spf1 ip4:192.227.228.86 -all。"
    if not text:
        return "验证码邮件发送失败，请稍后重试。"
    return "验证码邮件发送失败：" + text[:500]

def record_send(user_id, sender, recipient, subject, status, error=None):
    with DB_LOCK, db() as conn:
        conn.execute("insert into sent_messages(user_id,sender,recipient,subject,sent_at,status,error) values(?,?,?,?,?,?,?)", (user_id,sender,recipient,subject[:200],now_iso(),status,(error or "")[:1000])); conn.commit()

class TempMailSMTP(smtpd.SMTPServer):
    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        try:
            if isinstance(data, str): data=data.encode("utf-8","replace")
            return store_message(peer, mailfrom, rcpttos, data)
        except Exception as exc:
            print(f"smtp error: {exc}", file=sys.stderr, flush=True); return "451 temporary local error"

class Handler(BaseHTTPRequestHandler):
    server_version="TempMail/3.0"
    def end_headers(self):
        self.send_header("X-Content-Type-Options","nosniff")
        if getattr(self, "path", "").startswith("/admin"):
            self.send_header("X-Robots-Tag","noindex, nofollow")
        else:
            self.send_header("X-Robots-Tag","index, follow")
        super().end_headers()
    def send_json(self, payload, status=200, headers=None):
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body)))
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def send_text(self, text, status=200, ctype="text/plain; charset=utf-8", cache="public, max-age=300"):
        body=text.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Cache-Control",cache); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def send_bytes(self, body, filename, content_type):
        self.send_response(200); self.send_header("Content-Type",content_type or "application/octet-stream"); self.send_header("Content-Length",str(len(body))); self.send_header("Content-Disposition",f'attachment; filename="{filename}"'); self.end_headers(); self.wfile.write(body)
    def read_json(self):
        length=min(int(self.headers.get("content-length","0") or 0), 262144)
        if length<=0: return {}
        try: return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception: return {}
    def cookie_value(self, name):
        for part in self.headers.get("Cookie","").split(";"):
            if "=" not in part: continue
            k,v=part.strip().split("=",1)
            if k==name: return v
        return ""
    def current_user(self):
        token=self.cookie_value("tm_session")
        if not token: return None
        with DB_LOCK, db() as conn:
            return conn.execute("select u.* from sessions s join users u on u.id=s.user_id where s.token=? and s.expires_at>?", (token, now_iso())).fetchone()
    def require_user(self):
        row=self.current_user()
        if not row: raise PermissionError("login required")
        return row
    def require_admin(self):
        row=self.require_user()
        if row["role"]!="admin": raise PermissionError("admin required")
        return row

    def do_GET(self):
        purge_old(); parsed=urlparse(self.path); qs=parse_qs(parsed.query)
        try:
            if parsed.path=="/healthz": return self.send_json({"ok":True,"domain":DOMAIN,"version":"3.0"})
            if parsed.path=="/robots.txt": return self.send_text(f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: https://{DOMAIN}/sitemap.xml\n")
            if parsed.path=="/sitemap.xml":
                urls=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
                for lang in LANG_CODES: urls.append(f"<url><loc>https://{DOMAIN}/?lang={quote(lang)}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>")
                urls.append("</urlset>"); return self.send_text("\n".join(urls), 200, "application/xml; charset=utf-8")
            if parsed.path in ("/","/index.html"): return self.send_text(FINAL_PUBLIC_PAGE, 200, "text/html; charset=utf-8", "no-store")
            if parsed.path=="/admin": return self.send_text(ADMIN_PAGE, 200, "text/html; charset=utf-8", "no-store")
            if parsed.path=="/api/new": return self.send_json({"error":"use /api/create-mailbox"}, 410)
            if parsed.path=="/api/me":
                user=self.current_user(); return self.send_json({"user":user_payload(user) if user and user["role"]=="admin" else None})
            if parsed.path=="/api/messages":
                box=normalize_box(qs.get("box",[""])[0]); token=qs.get("token",[""])[0]
                if not mailbox_access_ok(box, token): raise PermissionError("mailbox token required")
                with DB_LOCK, db() as conn: rows=conn.execute("select id,sender,subject,received_at from messages where mailbox=? order by id desc limit 100", (box,)).fetchall()
                return self.send_json({"box":box,"address":f"{box}@{DOMAIN}","messages":[dict(r) for r in rows]})
            if parsed.path=="/api/message":
                box=normalize_box(qs.get("box",[""])[0]); token=qs.get("token",[""])[0]; mid=int(qs.get("id",["0"])[0])
                if not mailbox_access_ok(box, token): raise PermissionError("mailbox token required")
                with DB_LOCK, db() as conn:
                    row=conn.execute("select id,mailbox,recipient,sender,subject,received_at,text,raw from messages where mailbox=? and id=?", (box,mid)).fetchone(); atts=conn.execute("select id,filename,content_type,size from attachments where message_id=?", (mid,)).fetchall()
                if not row: return self.send_json({"error":"not found"}, 404)
                data=dict(row); data["attachments"]=[dict(a) for a in atts]; return self.send_json(data)
            if parsed.path=="/api/attachment":
                box=normalize_box(qs.get("box",[""])[0]); token=qs.get("token",[""])[0]; aid=int(qs.get("id",["0"])[0])
                if not mailbox_access_ok(box, token): raise PermissionError("mailbox token required")
                with DB_LOCK, db() as conn: att=conn.execute("select a.* from attachments a join messages m on m.id=a.message_id where a.id=? and m.mailbox=?", (aid,box)).fetchone()
                if not att: return self.send_json({"error":"not found"}, 404)
                return self.send_bytes(att["data"], att["filename"], att["content_type"])
            if parsed.path in ("/api/admin/messages","/api/admin/all-messages"):
                self.require_admin()
                with DB_LOCK, db() as conn:
                    rows=conn.execute("""select 'current' as source,m.id,m.mailbox,m.recipient,m.sender,m.subject,substr(m.text,1,240) as text,m.received_at,null as archived_at,(select count(*) from attachments a where a.message_id=m.id) as attachments,mc.ip,mc.fingerprint,mc.user_agent,mc.created_by from messages m left join mailbox_creations mc on mc.mailbox=m.mailbox union all select 'archive' as source,am.id,am.mailbox,am.recipient,am.sender,am.subject,substr(am.text,1,240),am.received_at,am.archived_at,(select count(*) from archived_attachments aa where aa.archived_message_id=am.id),mc.ip,mc.fingerprint,mc.user_agent,mc.created_by from archived_messages am left join mailbox_creations mc on mc.mailbox=am.mailbox order by received_at desc limit 1000""").fetchall()
                return self.send_json({"messages":[dict(r) for r in rows]})
            if parsed.path=="/api/admin/mailboxes":
                self.require_admin()
                with DB_LOCK, db() as conn: rows=conn.execute("select id,mailbox,created_at,local_date,ip,fingerprint,user_agent,created_by from mailbox_creations order by id desc limit 1000").fetchall()
                return self.send_json({"mailboxes":[dict(r) for r in rows]})
            if parsed.path=="/api/admin/message":
                self.require_admin(); source=qs.get("source",["current"])[0]; mid=int(qs.get("id",["0"])[0])
                with DB_LOCK, db() as conn:
                    if source=="archive": row=conn.execute("select 'archive' as source,am.*,mc.ip,mc.fingerprint,mc.user_agent,mc.created_by from archived_messages am left join mailbox_creations mc on mc.mailbox=am.mailbox where am.id=?", (mid,)).fetchone(); atts=conn.execute("select id,filename,content_type,size from archived_attachments where archived_message_id=?", (mid,)).fetchall()
                    else: row=conn.execute("select 'current' as source,m.*,mc.ip,mc.fingerprint,mc.user_agent,mc.created_by from messages m left join mailbox_creations mc on mc.mailbox=m.mailbox where m.id=?", (mid,)).fetchone(); atts=conn.execute("select id,filename,content_type,size from attachments where message_id=?", (mid,)).fetchall()
                if not row: return self.send_json({"error":"not found"}, 404)
                data=dict(row); data["attachments"]=[dict(a) for a in atts]; return self.send_json(data)
            if parsed.path=="/api/admin/attachment":
                self.require_admin(); source=qs.get("source",["current"])[0]; aid=int(qs.get("id",["0"])[0])
                with DB_LOCK, db() as conn: att=conn.execute(("select * from archived_attachments where id=?" if source=="archive" else "select * from attachments where id=?"), (aid,)).fetchone()
                if not att: return self.send_json({"error":"not found"}, 404)
                return self.send_bytes(att["data"], att["filename"], att["content_type"])
            return self.send_json({"error":"not found"}, 404)
        except PermissionError as exc: return self.send_json({"error":str(exc)}, 403)
        except ValueError as exc: return self.send_json({"error":str(exc)}, 400)
        except Exception as exc:
            print(f"http error: {exc}", file=sys.stderr, flush=True); return self.send_json({"error":"server error"}, 500)
    def do_POST(self):
        purge_old(); parsed=urlparse(self.path); data=self.read_json()
        try:
            if parsed.path=="/api/create-mailbox":
                try:
                    return self.send_json(create_guest_mailbox(client_ip(self), data.get("fingerprint") or "", self.headers.get("User-Agent", ""), data.get("box") or data.get("address") or ""))
                except RuntimeError as exc:
                    if "limit" in str(exc): return self.send_json({"error":"daily mailbox creation limit reached"}, 429)
                    if "exists" in str(exc): return self.send_json({"error":"mailbox already exists"}, 409)
                    raise
            if parsed.path in ("/api/request-code","/api/register"):
                return self.send_json({"error":"public registration is disabled"}, 410)
            if parsed.path=="/api/login":
                login=(data.get("login") or "").strip(); password=data.get("password") or ""
                with DB_LOCK, db() as conn:
                    row=conn.execute("select * from users where role='admin' and (lower(username)=lower(?) or lower(email)=lower(?))", (login,login.lower())).fetchone()
                if not row or not verify_password(password, row["salt"], row["password_hash"]): return self.send_json({"error":"invalid admin login"}, 401)
                token=create_session(row["id"])
                return self.send_json({"ok":True,"user":user_payload(row)}, headers={"Set-Cookie":f"tm_session={token}; Path=/; Max-Age={SESSION_DAYS*86400}; HttpOnly; SameSite=Lax"})
            if parsed.path=="/api/logout":
                token=self.cookie_value("tm_session")
                if token:
                    with DB_LOCK, db() as conn: conn.execute("delete from sessions where token=?", (token,)); conn.commit()
                return self.send_json({"ok":True}, headers={"Set-Cookie":"tm_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
            if parsed.path=="/api/send":
                user=self.require_admin(); from_local=normalize_admin_sender(data.get("fromLocal") or data.get("from") or ADMIN_USERNAME)
                ensure_admin_mailbox(from_local, self)
                recipient=normalize_outbound_email(data.get("to") or ""); subject=(data.get("subject") or "").strip()[:200]; body=(data.get("body") or "").strip()
                if not body: raise ValueError("body is required")
                sender=f"{from_local}@{DOMAIN}"
                try:
                    result=deliver_email(sender, recipient, subject, body, from_local); record_send(user["id"], sender, recipient, subject, "sent", "")
                    return self.send_json({"ok":True,"result":result,"user":user_payload(user)})
                except Exception as exc:
                    msg=friendly_delivery_error(exc); record_send(user["id"], sender, recipient, subject, "failed", msg); return self.send_json({"error":msg}, 502)
            if parsed.path=="/api/delete":
                box=normalize_box(data.get("box", "")); token=data.get("token", ""); mid=int(data.get("id", 0))
                if not mailbox_access_ok(box, token): raise PermissionError("mailbox token required")
                with DB_LOCK, db() as conn:
                    conn.execute("delete from attachments where message_id in (select id from messages where mailbox=? and id=?)", (box,mid)); conn.execute("delete from messages where mailbox=? and id=?", (box,mid)); conn.commit()
                return self.send_json({"ok":True})
            if parsed.path=="/api/clear":
                box=normalize_box(data.get("box", "")); token=data.get("token", "")
                if not mailbox_access_ok(box, token): raise PermissionError("mailbox token required")
                with DB_LOCK, db() as conn:
                    conn.execute("delete from attachments where message_id in (select id from messages where mailbox=?)", (box,)); conn.execute("delete from messages where mailbox=?", (box,)); conn.commit()
                return self.send_json({"ok":True})
            return self.send_json({"error":"not found"}, 404)
        except PermissionError as exc: return self.send_json({"error":str(exc)}, 403)
        except ValueError as exc: return self.send_json({"error":str(exc)}, 400)
        except Exception as exc:
            print(f"http error: {exc}", file=sys.stderr, flush=True); return self.send_json({"error":"server error"}, 500)
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.client_address[0], fmt % args), flush=True)

def run_smtp():
    TempMailSMTP((SMTP_HOST, SMTP_PORT), None, decode_data=False, data_size_limit=MAX_MESSAGE_BYTES)
    print(f"smtp listening on {SMTP_HOST}:{SMTP_PORT}", flush=True); asyncore.loop(timeout=1)

def shutdown(signum, frame):
    print("stopping", flush=True); sys.exit(0)

def main():
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    init_db(); archive_due_messages(); purge_old()
    threading.Thread(target=archive_loop, daemon=True).start()
    threading.Thread(target=run_smtp, daemon=True).start()
    httpd=ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print(f"http listening on {HTTP_HOST}:{HTTP_PORT}; domain={DOMAIN}", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    main()
