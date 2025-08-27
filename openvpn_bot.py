import os
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import TOKEN, EASYRSA_DIR, OUTPUT_DIR, TA_KEY_PATH, SERVER_IP, ADMIN_ID

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
        subprocess.run(f"cd {EASYRSA_DIR} && EASYRSA_BATCH=1 ./easyrsa gen-req {clientname} nopass", shell=True, check=True)
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

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", newclient))
    print("Бот запущен!")
    app.run_polling()
