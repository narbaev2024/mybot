import telebot
from datetime import datetime, timedelta
import psycopg2
import pytz
import logging
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)

timezone = pytz.timezone('Asia/Bishkek')

API_TOKEN = '7370432818:AAELlwGFnwnq0J7flE1gZsDhyG3wnJRuaCY'
bot = telebot.TeleBot(API_TOKEN)

# PostgreSQL connection
conn = psycopg2.connect(
    dbname='keybot',
    user='postgres',
    password='adminadmin',
    host='localhost',
    port='5432'
)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS certificates (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        user_name TEXT,
        certificate_name TEXT,
        certificate_key TEXT,
        expiration_date TIMESTAMP
    );
''')
conn.commit()

user_states = {}

@bot.message_handler(commands=['start'])
def start_command(message):
    show_menu(message)

def show_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button_add = types.KeyboardButton("/add")
    button_remove = types.KeyboardButton("/remove")
    button_check = types.KeyboardButton("/certificate")
    button_update = types.KeyboardButton("/update")
    button_help = types.KeyboardButton("/help")
    markup.add(button_add, button_remove, button_check, button_update, button_help)
    bot.send_message(message.chat.id, "Выберите команду:", reply_markup=markup)

def cancel_keyboard():
    markup = types.InlineKeyboardMarkup()
    button_cancel = types.InlineKeyboardButton("Отмена", callback_data="cancel")
    markup.add(button_cancel)
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_command(call):
    user_id = call.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        bot.answer_callback_query(call.id, "✅ Процесс отменён.")
        bot.send_message(user_id, "Процесс отменён. Вы можете использовать другие команды.")
    else:
        bot.answer_callback_query(call.id, "🔄 Нет активного процесса для отмены.")

@bot.message_handler(commands=['add'])
def start_add_certificate(message):
    user_states[message.from_user.id] = {'step': 1}
    bot.reply_to(message, "Введите название сертификата в кавычках:", reply_markup=cancel_keyboard())

@bot.message_handler(commands=['remove'])
def remove_certificate(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        bot.reply_to(message, "✅ Процесс отменён. Теперь вы можете ввести новую команду.")
        return
    if len(message.text.split()) < 2:
        bot.reply_to(message, "⚠️ Использование: /remove <название сертификата>")
        return
    name = message.text.split(maxsplit=1)[1].strip('"')
    cursor.execute("DELETE FROM certificates WHERE user_id = %s AND certificate_name = %s", (user_id, name))
    conn.commit()
    if cursor.rowcount > 0:
        bot.reply_to(message, f"✅ Сертификат *'{name}'* удален.")
    else:
        bot.reply_to(message, f"🚫 Сертификат *'{name}'* не найден.")

@bot.message_handler(commands=['update'])
def start_update_certificate(message):
    user_states[message.from_user.id] = {'step': 1, 'update': True}
    bot.reply_to(message, "Введите название сертификата для обновления в кавычках:", reply_markup=cancel_keyboard())

@bot.message_handler(func=lambda message: message.from_user.id in user_states)
def handle_add_or_update_certificate_input(message):
    user_id = message.from_user.id
    step = user_states[user_id]['step']

    if step == 1:
        if message.text.startswith('"') and message.text.endswith('"'):
            certificate_name = message.text.strip('"')
            user_states[user_id]['certificate_name'] = certificate_name

            if 'update' in user_states[user_id]:
                user_states[user_id]['step'] = 2
                bot.reply_to(message, "Введите новую дату истечения в формате ГГГГ-ММ-ДД ЧЧ:MM:",
                             reply_markup=cancel_keyboard())
            else:
                user_states[user_id]['step'] = 2
                bot.reply_to(message, "Введите ключ сертификата в кавычках:", reply_markup=cancel_keyboard())
        else:
            bot.reply_to(message, "❌ Пожалуйста, введите название сертификата в кавычках.")

    elif step == 2:
        if 'update' in user_states[user_id]:
            try:
                expiration_date = datetime.strptime(message.text, '%Y-%m-%d %H:%M')
                certificate_name = user_states[user_id]['certificate_name']
                update_certificate(user_id, certificate_name, expiration_date)
                bot.reply_to(message, f"✅ Дата истечения сертификата *'{certificate_name}'* обновлена.")
            except ValueError:
                bot.reply_to(message, "❌ Неверный формат даты. Пожалуйста, используйте формат ГГГГ-ММ-ДД ЧЧ:MM.")
            finally:
                del user_states[user_id]
        else:
            if message.text.startswith('"') and message.text.endswith('"'):
                user_states[user_id]['certificate_key'] = message.text.strip('"')
                user_states[user_id]['step'] = 3
                bot.reply_to(message, "Введите дату истечения в формате ГГГГ-ММ-ДД ЧЧ:MM:",
                             reply_markup=cancel_keyboard())
            else:
                bot.reply_to(message, "❌ Пожалуйста, введите ключ сертификата в кавычках.")

    elif step == 3:
        try:
            expiration_date = datetime.strptime(message.text, '%Y-%m-%d %H:%M')
            add_certificate(user_id, message.from_user.full_name, user_states[user_id]['certificate_name'],
                            user_states[user_id]['certificate_key'], expiration_date)
            bot.reply_to(message, f"✅ Сертификат *'{user_states[user_id]['certificate_name']}'* добавлен.")
        except ValueError:
            bot.reply_to(message, "❌ Неверный формат даты. Пожалуйста, используйте формат ГГГГ-ММ-ДД ЧЧ:MM.")
        finally:
            del user_states[user_id]

def add_certificate(user_id, user_name, certificate_name, certificate_key, expiration_date):
    cursor.execute(
        "INSERT INTO certificates (user_id, user_name, certificate_name, certificate_key, expiration_date) VALUES (%s, %s, %s, %s, %s)",
        (user_id, user_name, certificate_name, certificate_key, expiration_date))
    conn.commit()

def update_certificate(user_id, certificate_name, expiration_date):
    cursor.execute("UPDATE certificates SET expiration_date = %s WHERE user_id = %s AND certificate_name = %s",
                   (expiration_date, user_id, certificate_name))
    conn.commit()

@bot.message_handler(commands=['certificate'])
def check_certificates(message):
    logging.info(f"Пользователь {message.from_user.id} запрашивает сертификаты.")

    try:
        cursor.execute("SELECT certificate_name, certificate_key, expiration_date FROM certificates WHERE user_id = %s",
                       (message.from_user.id,))
        rows = cursor.fetchall()
    except psycopg2.Error as e:
        logging.error(f"Ошибка при выполнении запроса: {e}")
        bot.reply_to(message, "Произошла ошибка при получении сертификатов.")
        return

    if rows:
        response = "*Ваши сертификаты:*\n"
        for name, certificate_key, expiration_date in rows:
            response += f"🔖 Сертификат: *\"{name}\"*\n🔑 Ключ: \"{certificate_key}\"\n📅 Дата истечения: {expiration_date}\n\n"
    else:
        response = "🚫 У вас нет добавленных сертификатов."

    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.reply_to(message, "Доступные команды:\n"
                          "/add - Добавить сертификат\n"
                          "/remove - Удалить сертификат\n"
                          "/certificate - Проверить сертификаты\n"
                          "/update - Обновить дату истечения сертификата\n"
                          "/cancel - Отменить текущую операцию",
                 parse_mode='Markdown')

def send_reminders():
    current_time = datetime.now(timezone)
    threshold_time = current_time + timedelta(days=1)

    cursor.execute("SELECT user_id, certificate_name, expiration_date FROM certificates WHERE expiration_date <= %s",
                   (threshold_time,))
    rows = cursor.fetchall()

    for user_id, certificate_name, expiration_date in rows:
        bot.send_message(user_id,
                         f"🔔 Внимание: сертификат *'{certificate_name}'* истекает {expiration_date}. Пожалуйста, обновите или удалите его!")

scheduler = BackgroundScheduler()
scheduler.add_job(send_reminders, 'interval', minutes=15)
scheduler.start()

try:
    bot.polling(none_stop=True)
except KeyboardInterrupt:
    scheduler.shutdown()
    cursor.close()
    conn.close()

