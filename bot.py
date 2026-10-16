import os
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot attivo!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web, daemon=True).start()
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TOKEN")

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

# --- TRACCIAMENTO MESSAGGI ---
async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
        return

    user = update.effective_user
    if user.is_bot:
        return

    chat_id = update.effective_chat.id
    now = datetime.now()

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_activity (user_id, chat_id, username, full_name, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            last_seen = excluded.last_seen
    ''', (user.id, chat_id, user.username, user.full_name, now))
    conn.commit()
    conn.close()

# --- COMANDO DI VERIFICA (SOLO LISTA, NESSUN BAN) ---
async def verify_inactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Questo comando puo essere usato solo nei gruppi.")
        return

    chat = update.effective_chat
    user_member = await chat.get_member(update.effective_user.id)
    
    if user_member.status not in ['administrator', 'creator']:
        await update.message.reply_text("Solo gli amministratori possono usare questo comando.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Per favore specifica il numero di giorni (da 1 a 30).\n"
            "Esempio: /verifica 7 (per vedere chi non scrive da 7 giorni)"
        )
        return

    days = int(context.args[0])

    if days < 1 or days > 30:
        await update.message.reply_text("Puoi scegliere un valore compreso tra 1 e 30 giorni.")
        return

    cutoff_date = datetime.now() - timedelta(days=days)

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name, last_seen 
        FROM user_activity 
        WHERE chat_id = ? AND last_seen < ?
    ''', (chat.id, cutoff_date))
    inactive_users = cursor.fetchall()
    conn.close()

    if not inactive_users:
        await update.message.reply_text(f"Nessun utente inattivo trovato da piu di {days} giorni.")
        return

    report = f"Utenti inattivi da piu di {days} giorni (nessun ban eseguito):\n\n"
    for user_id, username, full_name, last_seen in inactive_users:
        name = f"@{username}" if username else full_name
        report += f"- {name} (Ultimo accesso: {last_seen})\n"

    await update.message.reply_text(report)

# --- COMANDO PER SCEGLIERE I GIORNI E BANNARE ---
async def ban_inactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Questo comando puo essere usato solo nei gruppi.")
        return

    chat = update.effective_chat
    user_member = await chat.get_member(update.effective_user.id)
    
    if user_member.status not in ['administrator', 'creator']:
        await update.message.reply_text("Solo gli amministratori possono usare questo comando.")
        return

    bot_member = await chat.get_member(context.bot.id)
    if not bot_member.can_restrict_members:
        await update.message.reply_text("Non ho i permessi per bannare gli utenti! Assicurati di darmi i permessi da amministratore per la gestione utenti.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Per favore specifica il numero di giorni (da 1 a 30).\n"
            "Esempio: /ban_inattivi 7 (per bannare chi non scrive da 7 giorni)"
        )
        return

    days = int(context.args[0])

    if days < 1 or days > 30:
        await update.message.reply_text("Puoi scegliere un valore compreso tra 1 e 30 giorni.")
        return

    cutoff_date = datetime.now() - timedelta(days=days)

    conn = sqlite3.connect("activity.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name, last_seen 
        FROM user_activity 
        WHERE chat_id = ? AND last_seen < ?
    ''', (chat.id, cutoff_date))
    inactive_users = cursor.fetchall()
    conn.close()

    if not inactive_users:
        await update.message.reply_text(f"Nessun utente inattivo da piu di {days} giorni.")
        return

    banned_count = 0
    banned_list = []

    for user_id, username, full_name, last_seen in inactive_users:
        try:
            member = await chat.get_member(user_id)
            if member.status in ['administrator', 'creator'] or member.user.is_bot:
                continue
            
            await chat.ban_member(user_id)
            
            conn = sqlite3.connect("activity.db")
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_activity WHERE user_id = ? AND chat_id = ?', (user_id, chat.id))
            conn.commit()
            conn.close()

            name = f"@{username}" if username else full_name
            banned_list.append(name)
            banned_count += 1
        except Exception as e:
            print(f"Impossibile bannare l'utente {user_id}: {e}")

    if banned_count > 0:
        report = f"Pulizia inattivi completata ({days} giorni):\nBannati {banned_count} utenti:\n" + ", ".join(banned_list)
        await update.message.reply_text(report)
    else:
        await update.message.reply_text("Nessun utente idoneo al ban trovato (potrebbero essere tutti admin).")

# --- AVVIO DEL BOT ---
   
setup_db()

application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("verifica", verify_inactive_command))
application.add_handler(CommandHandler("ban_inattivi", ban_inactive_command))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_activity))

def run_bot():
    print("Bot in ascolto con comando di verifica...")
    application.run_polling(stop_signals=None)

Thread(target=run_bot, daemon=True).start()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=10000, use_reloader=False)

