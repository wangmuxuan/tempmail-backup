# TempMail Backup

这是从线上服务器整理出来的临时邮箱项目备份版，已经额外做了两项适合公开仓库的处理：

- 去掉了源码里的管理员硬编码账号和密码哈希，改为环境变量配置。
- 提供了 `systemd` 服务文件和环境变量示例文件，方便重新部署。

## 目录结构

```text
src/tempmail.py              主程序
deploy/tempmail.service      systemd 服务文件
deploy/tempmail.env.example  环境变量示例
```

## 运行要求

- Linux 服务器
- Python 3.10 或更高版本
- `systemd`
- 对外开放的 `80` 和 `25` 端口
- 已解析到服务器的域名

## 快速安装

以下步骤以 Ubuntu 或 Debian 为例。

### 1. 安装基础环境

```bash
apt update
apt install -y python3
```

### 2. 创建目录和系统用户

```bash
useradd --system --home /opt/tempmail --shell /usr/sbin/nologin tempmail
mkdir -p /opt/tempmail /var/lib/tempmail /etc/tempmail
chown -R tempmail:tempmail /opt/tempmail /var/lib/tempmail
chmod 755 /opt/tempmail /var/lib/tempmail /etc/tempmail
```

### 3. 上传程序文件

把以下文件放到服务器：

- `src/tempmail.py` -> `/opt/tempmail/tempmail.py`
- `deploy/tempmail.service` -> `/etc/systemd/system/tempmail.service`
- `deploy/tempmail.env.example` -> `/etc/tempmail/tempmail.env`

然后执行：

```bash
chown tempmail:tempmail /opt/tempmail/tempmail.py
chmod 644 /opt/tempmail/tempmail.py
chmod 644 /etc/systemd/system/tempmail.service
chmod 600 /etc/tempmail/tempmail.env
```

### 4. 修改环境变量

编辑 `/etc/tempmail/tempmail.env`，至少改这些值：

```env
TEMPMAIL_DOMAIN=mail.example.com
TEMPMAIL_ADMIN_USERNAME=admin
TEMPMAIL_ADMIN_EMAIL=admin@mail.example.com
TEMPMAIL_ADMIN_PASSWORD=ChangeThisStrongPassword
```

常用可选项：

```env
TEMPMAIL_DB=/var/lib/tempmail/messages.db
TEMPMAIL_TTL_HOURS=24
TEMPMAIL_HTTP_PORT=80
TEMPMAIL_SMTP_PORT=25
TEMPMAIL_DAILY_SEND_LIMIT=5
TEMPMAIL_MAILBOX_DAILY_LIMIT=0
```

说明：

- `TEMPMAIL_MAILBOX_DAILY_LIMIT=0` 表示不限制每日创建邮箱数量。
- `TEMPMAIL_ADMIN_PASSWORD` 建议改成高强度密码，不要直接使用示例值。
- 如果你更想存哈希，也可以不填 `TEMPMAIL_ADMIN_PASSWORD`，改为提供 `TEMPMAIL_ADMIN_SALT` 和 `TEMPMAIL_ADMIN_PASSWORD_HASH`。

### 5. 启动服务

```bash
systemctl daemon-reload
systemctl enable --now tempmail
systemctl status tempmail --no-pager
```

### 6. 验证是否正常

```bash
curl http://127.0.0.1/healthz
```

正常会返回类似：

```json
{"ok":true,"domain":"mail.example.com","version":"3.0"}
```

## DNS 建议

至少要配置：

- `A` 记录: 把你的域名指向服务器 IP
- `MX` 记录: 指向该域名
- `SPF` 记录: `v=spf1 ip4:你的服务器IP -all`

如果你需要更高送达率，建议继续补：

- `PTR`
- `DKIM`
- `DMARC`

## 防火墙端口

至少放行：

- `80/tcp`
- `25/tcp`

如果站点前面有反向代理，也要确认代理能正确转发 HTTP 请求。

## 后台登录

程序启动后，会按照环境变量自动初始化管理员账号。后台登录使用：

- 用户名: `TEMPMAIL_ADMIN_USERNAME`
- 或邮箱: `TEMPMAIL_ADMIN_EMAIL`
- 密码: `TEMPMAIL_ADMIN_PASSWORD`

## 备份建议

建议把下面几项一起备份：

- `/opt/tempmail/tempmail.py`
- `/etc/systemd/system/tempmail.service`
- `/etc/tempmail/tempmail.env`
- `/var/lib/tempmail/messages.db`

这样以后迁移服务器时可以直接恢复。
