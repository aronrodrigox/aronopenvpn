import os
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import TOKEN, EASYRSA_DIR, OUTPUT_DIR, TA_KEY_PATH, SERVER_IP, ADMIN_ID
from telegram.constants import ParseMode

OVPN_TEMPLATE = """
client
dev tun
proto udp
remote {server_ip} 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-CBC
verb 3
<ca>
{ca}
</ca>
<cert>
{cert}
</cert>
<key>
{key}
</key>
<tls-auth>
{ta}
</tls-auth>
key-direction 1
"""

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
            return
        return await func(update, context)
    return wrapper

@admin_only
async def newclient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка на администратора
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /new clientname")
        return
    clientname = context.args[0]
    await update.message.reply_text(f"Генерирую ключи для {clientname}...")

    # Генерация ключей через easy-rsa
    try:
        subprocess.run(f"cd {EASYRSA_DIR} && EASYRSA_BATCH=1 EASYRSA_REQ_CN={clientname} ./easyrsa gen-req {clientname} nopass", shell=True, check=True)
        subprocess.run(f"cd {EASYRSA_DIR} && echo yes | EASYRSA_BATCH=1 ./easyrsa sign-req client {clientname}", shell=True, check=True)
    except subprocess.CalledProcessError:
        await update.message.reply_text("Ошибка при генерации ключей!")
        return

    # Пути к файлам
    ca_path = os.path.join(EASYRSA_DIR, "pki", "ca.crt")
    cert_path = os.path.join(EASYRSA_DIR, "pki", "issued", f"{clientname}.crt")
    key_path = os.path.join(EASYRSA_DIR, "pki", "private", f"{clientname}.key")
    ta_path = TA_KEY_PATH

    # Чтение файлов
    try:
        with open(ca_path) as f: ca = f.read()
        with open(cert_path) as f: cert = f.read()
        with open(key_path) as f: key = f.read()
        with open(ta_path) as f: ta = f.read()
    except Exception as e:
        await update.message.reply_text(f"Ошибка чтения файлов: {e}")
        return

    # Генерация ovpn
    ovpn_content = OVPN_TEMPLATE.format(
        ca=ca, cert=cert, key=key, ta=ta, server_ip=SERVER_IP
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ovpn_path = os.path.join(OUTPUT_DIR, f"{clientname}.ovpn")
    with open(ovpn_path, "w") as f:
        f.write(ovpn_content)

    # Отправка файла
    with open(ovpn_path, "rb") as f:
        await update.message.reply_document(f, filename=f"{clientname}.ovpn")

    await update.message.reply_text("Готово! Используй этот файл для подключения.")

@admin_only
async def list_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.ovpn')]
        if not files:
            await update.message.reply_text("📂 Нет сгенерированных клиентов.", parse_mode=ParseMode.HTML)
            return
        msg = "<b>📄 Список клиентов:</b>\n" + "\n".join(f"• <code>{f}</code>" for f in files)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@admin_only
async def get_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /get <имя_клиента>")
        return
    clientname = context.args[0]
    ovpn_path = os.path.join(OUTPUT_DIR, f"{clientname}.ovpn")
    if not os.path.exists(ovpn_path):
        await update.message.reply_text("❌ Такой клиент не найден.")
        return
    with open(ovpn_path, "rb") as f:
        await update.message.reply_document(f, filename=f"{clientname}.ovpn")

@admin_only
async def delete_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /delete <имя_клиента>")
        return
    clientname = context.args[0]
    removed = False
    # Удаляем ovpn
    ovpn_path = os.path.join(OUTPUT_DIR, f"{clientname}.ovpn")
    if os.path.exists(ovpn_path):
        os.remove(ovpn_path)
        removed = True
    # Удаляем ключи и сертификаты
    for path in [
        os.path.join(EASYRSA_DIR, "pki", "issued", f"{clientname}.crt"),
        os.path.join(EASYRSA_DIR, "pki", "private", f"{clientname}.key"),
        os.path.join(EASYRSA_DIR, "pki", "reqs", f"{clientname}.req")
    ]:
        if os.path.exists(path):
            os.remove(path)
            removed = True
    if removed:
        await update.message.reply_text(f"🗑 Клиент <b>{clientname}</b> удалён.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Такой клиент не найден.")

@admin_only
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.ovpn')]
        count = len(files)
        await update.message.reply_text(f"ℹ️ <b>Клиентов создано:</b> <b>{count}</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@admin_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>🛠 Доступные команды:</b>\n"
        "➕ /new [имя_клиента] — создать новый .ovpn-файл\n"
        "📄 /list — список клиентов\n"
        "📥 /get [имя_клиента] — получить .ovpn-файл\n"
        "🗑 /delete [имя_клиента] — удалить клиента\n"
        "ℹ️ /info — статус сервера\n"
        "📊 /stats — статистика трафика по клиентам\n"
        "🟢 /active — список активных пользователей\n"
        "🆘 /help — справка\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_path = "/etc/openvpn/openvpn-status.log"
    if not os.path.exists(status_path):
        await update.message.reply_text("Файл openvpn-status.log не найден.")
        return
    stats = []
    try:
        with open(status_path) as f:
            lines = f.readlines()
        found_clients = False
        for line in lines:
            # Новый формат: CLIENT_LIST,CommonName,RealAddress,BytesReceived,BytesSent,ConnectedSince,...
            if line.startswith("CLIENT_LIST"):
                parts = line.strip().split(",")
                cn = parts[1]
                rx = int(parts[3])
                tx = int(parts[4])
                stats.append(f"• <b>{cn}</b> — Rx: {rx/1024/1024:.2f} MB, Tx: {tx/1024/1024:.2f} MB")
                found_clients = True
        if not found_clients:
            # Старый формат: ищем после заголовка Common Name,Real Address,...
            for idx, line in enumerate(lines):
                if line.strip().startswith("Common Name,Real Address"):
                    for data_line in lines[idx+1:]:
                        data_line = data_line.strip()
                        if not data_line or "," not in data_line or data_line.startswith("ROUTING TABLE"):
                            break
                        parts = data_line.split(",")
                        if len(parts) >= 5:
                            cn = parts[0]
                            rx = int(parts[2])
                            tx = int(parts[3])
                            stats.append(f"• <b>{cn}</b> — Rx: {rx/1024/1024:.2f} MB, Tx: {tx/1024/1024:.2f} MB")
        if stats:
            msg = "👤 <b>Статистика трафика:</b>\n" + "\n".join(stats)
        else:
            msg = "Нет активных клиентов."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@admin_only
async def active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_path = "/etc/openvpn/openvpn-status.log"
    if not os.path.exists(status_path):
        await update.message.reply_text("Файл openvpn-status.log не найден.")
        return
    users = []
    try:
        with open(status_path) as f:
            lines = f.readlines()
        found_clients = False
        for idx, line in enumerate(lines):
            # Новый формат: CLIENT_LIST,cn,ip,...
            if line.startswith("CLIENT_LIST"):
                parts = line.strip().split(",")
                cn = parts[1]
                ip = parts[2].split(":")[0]
                since = parts[7] if len(parts) > 7 else "?"
                users.append(f"• <b>{cn}</b> — {ip} — с {since}")
                found_clients = True
            # Старый формат: ищем после заголовка Common Name,Real Address,...
        if not found_clients:
            # Найти индекс строки с заголовком
            for idx, line in enumerate(lines):
                if line.strip().startswith("Common Name,Real Address"):
                    # Все строки после заголовка до пустой строки или другого раздела
                    for data_line in lines[idx+1:]:
                        data_line = data_line.strip()
                        if not data_line or "," not in data_line or data_line.startswith("ROUTING TABLE"):
                            break
                        parts = data_line.split(",")
                        if len(parts) >= 5:
                            cn = parts[0]
                            ip = parts[1].split(":")[0]
                            since = parts[4]
                            users.append(f"• <b>{cn}</b> — {ip} — с {since}")
        if users:
            msg = "🟢 <b>Активные пользователи:</b>\n" + "\n".join(users)
        else:
            msg = "Нет активных клиентов."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands = (
        "👋 <b>Добро пожаловать в OpenVPN Бот!</b>\n\n"
        "🛠 <b>Доступные команды:</b>\n"
        "➕ /new [имя_клиента] — создать новый .ovpn-файл\n"
        "📄 /list — список клиентов\n"
        "📥 /get [имя_клиента] — получить .ovpn-файл\n"
        "🗑 /delete [имя_клиента] — удалить клиента\n"
        "ℹ️ /info — статус сервера\n"
        "🆘 /help — справка\n"
    )
    await update.message.reply_text(commands, parse_mode=ParseMode.HTML)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", newclient))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_clients))
    app.add_handler(CommandHandler("get", get_client))
    app.add_handler(CommandHandler("delete", delete_client))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("active", active))
    print("Бот запущен!")
    app.run_polling()
