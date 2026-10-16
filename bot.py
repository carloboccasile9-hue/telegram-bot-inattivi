import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# --- CONFIGURAZIONE WEB SERVER (Flask per Render) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Il bot Telegram è attivo e in esecuzione!"

# --- INIZIALIZZAZIONE DATABASE ---
def setup_db():
    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            full_name TEXT,
            last_seen TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    conn.commit()
    conn.close()

# --- TRACCIAMENTO ATTIVITÀ ---
async def track_activity(update: Update, context):
    if not update.effective_user or not update.effective_chat:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    # Ignora i messaggi nei canali o dove non c'è un utente valido
    if user.is_bot:
        return

    user_id = user.id
    chat_id = chat.id
    username = user.username or ""
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    now = datetime.utcnow()

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_activity (user_id, chat_id, username, full_name, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            last_seen=excluded.last_seen
    ''', (user_id, chat_id, username, full_name, now))
    conn.commit()
    conn.close()

# --- COMANDO DI VERIFICA ---
async def verify_inactive_command(update: Update, context):
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    args = context.args
    
    # Default: 30 giorni di inattività
    days = 30
    if args and args[0].isdigit():
        days = int(args[0])

    threshold = datetime.utcnow() - timedelta(days=days)

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, full_name, username, last_seen 
        FROM user_activity 
        WHERE chat_id = ? AND last_seen < ?
    ''', (chat_id, threshold))
    inactive_users = cursor.fetchall()
    conn.close()

    if inactive_users:
        report = f"Utenti inattivi da più di {days} giorni:\n\n"
        for user_id, full_name, username, last_seen in inactive_users:
            uname = f"@{username}" if username else "Nessun username"
            report.format()
            report += f"- {full_name} ({uname}) - Ultima vista: {last_seen}\n"
        await update.message.reply_text(report)
    else:
        await update.message.reply_text(f"Nessun utente inattivo trovato da oltre {days} giorni.")

# --- COMANDO DI BAN INATTIVI ---
async def ban_inactive_command(update: Update, context):
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    args = context.args
    
    days = 30
    if args and args[0].isdigit():
        days = int(args[0])

    threshold = datetime.utcnow() - timedelta(days=days)

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, full_name FROM user_activity 
        WHERE chat_id = ? AND last_seen < ?
    ''', (chat_id, threshold))
    inactive_users = cursor.fetchall()
    conn.close()

    banned_count = 0
    for user_id, full_name in inactive_users:
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            banned_count += 1
        except Exception as e:
            print(f"Impossibile bannare {user_id}: {e}")

    await update.message.reply_text(f"Pulizia inattivi completata ({days} giorni):\nBannati {banned_count} utenti.")

# --- LETTURA TOKEN DA VARIABILE D'AMBIENTE ---
TOKEN = os.environ.get("TOKEN")

# --- AVVIO DEL BOT ---
setup_db()

application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("verifica", verify_inactive_command))
application.add_handler(CommandHandler("ban_inattivi", ban_inactive_command))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_activity))

def run_bot():
    print("Bot in ascolto con comando di verifica...")
    application.run_polling(stop_signals=None)

# Avviamo il bot Telegram in un thread separato
Thread(target=run_bot, daemon=True).start()

# Avviamo il web server per Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
