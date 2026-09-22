import telebot
from telebot import types
import requests
import time
import threading
import sqlite3
import datetime
from flask import Flask
from threading import Thread

TOKEN = "8704937440:AAE2giwzq-9eFPT0FrwTJ4ApuetW5HuC7pI"
API_KEY = "3346c861411945f05ce3135adee75c6b"
ADMIN_ID = 1682561630 

bot = telebot.TeleBot(TOKEN)
HEADERS = {'x-apisports-key': API_KEY}
signaled_matches = set()

# ==========================================
# 1. БАЗА ДАННЫХ
# ==========================================
conn = sqlite3.connect('radar.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT)')
try:
    cursor.execute("ALTER TABLE users ADD COLUMN signals_today INTEGER DEFAULT 0")
    cursor.execute("ALTER TABLE users ADD COLUMN last_signal_date TEXT DEFAULT ''")
    cursor.execute("ALTER TABLE users ADD COLUMN vip_until INTEGER DEFAULT 0")
    cursor.execute("ALTER TABLE users ADD COLUMN referrals INTEGER DEFAULT 0")
    conn.commit()
except Exception:
    pass

cursor.execute('CREATE TABLE IF NOT EXISTS stats (wins INTEGER, losses INTEGER)')
cursor.execute('SELECT * FROM stats')
if not cursor.fetchone():
    cursor.execute('INSERT INTO stats (wins, losses) VALUES (0, 0)')

cursor.execute('''CREATE TABLE IF NOT EXISTS tracked_bets_v2 (
    fixture_id INTEGER, 
    home_team TEXT, 
    away_team TEXT, 
    bet_type TEXT, 
    bet_val TEXT, 
    target_value REAL, 
    odd REAL, 
    prediction_text TEXT
)''')
conn.commit()

def add_user(user_id, ref_id=None):
    cursor.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO users (user_id, status, signals_today, last_signal_date, vip_until, referrals) VALUES (?, ?, 0, "", 0, 0)', (user_id, 'free'))
        conn.commit()
        if ref_id and ref_id != user_id:
            cursor.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id=?", (ref_id,))
            conn.commit()
            return True
    return False

def get_all_users():
    current_time = int(time.time())
    cursor.execute("UPDATE users SET status='FREE' WHERE status='VIP' AND vip_until > 0 AND vip_until < ?", (current_time,))
    conn.commit()
    cursor.execute('SELECT user_id, status FROM users')
    return cursor.fetchall()

# ==========================================
# 2. ПРИЕМ ОПЛАТЫ И АДМИНКА
# ==========================================
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    user_id = message.chat.id
    expire_time = int(time.time()) + (7 * 24 * 3600)
    cursor.execute("UPDATE users SET status='VIP', vip_until=? WHERE user_id=?", (expire_time, user_id))
    conn.commit()
    bot.send_message(user_id, "✅ <b>Оплата прошла успешно!</b>\n\n💎 VIP-доступ на <b>1 неделю</b> активирован.", parse_mode="HTML")
    bot.send_message(ADMIN_ID, f"💰 <b>НОВАЯ ОПЛАТА! 50 Stars</b>\nПользователь <code>{user_id}</code> купил подписку!")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id == ADMIN_ID:
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE status='VIP'")
        vips = cursor.fetchone()[0]
        cursor.execute('SELECT wins, losses FROM stats')
        wins, losses = cursor.fetchone()
        text = f"👑 <b>ПАНЕЛЬ СОЗДАТЕЛЯ</b>\n\n👥 Клиентов: {total} (VIP: {vips})\n✅ Плюсов: {wins} | ❌ Минусов: {losses}\n\nВыдать VIP: <code>/addvip [ID]</code>\nРассылка: <code>/send [текст]</code>\nПредматч: <code>/prematch</code>\nБэкап: <code>/backup</code>"
        bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        try:
            with open('radar.db', 'rb') as doc:
                bot.send_document(message.chat.id, doc, caption="📦 Резервная копия базы данных")
        except Exception:
            bot.send_message(ADMIN_ID, "❌ Ошибка при создании бэкапа.")

@bot.message_handler(commands=['addvip'])
def give_vip(message):
    if message.chat.id == ADMIN_ID:
        try:
            user_id = int(message.text.split()[1])
            expire_time = int(time.time()) + (7 * 24 * 3600)
            cursor.execute("UPDATE users SET status='VIP', vip_until=? WHERE user_id=?", (expire_time, user_id))
            conn.commit()
            bot.send_message(ADMIN_ID, f"✅ VIP выдан {user_id}!")
        except Exception:
            bot.send_message(ADMIN_ID, "❌ Ошибка! Формат: /addvip ID")

@bot.message_handler(commands=['send'])
def broadcast_message(message):
    if message.chat.id == ADMIN_ID:
        text = message.text.replace("/send", "").strip()
        if text:
            for u in get_all_users():
                try: bot.send_message(u[0], text)
                except Exception: pass
            bot.send_message(ADMIN_ID, "✅ Рассылка завершена.")

@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID and message.reply_to_message is not None)
def admin_reply_to_user(message):
    original_text = message.reply_to_message.text
    if "Юзер ID:" in original_text:
        try:
            user_id = int(original_text.split("Юзер ID: ")[1].split("\n")[0].strip())
            bot.send_message(user_id, f"👨‍💻 <b>Ответ от Поддержки:</b>\n\n{message.text}", parse_mode="HTML")
            bot.reply_to(message, "✅ Успешно отправлено!")
        except Exception: pass

# ==========================================
# 3. МЕНЮ И НАВИГАЦИЯ
# ==========================================
def get_main_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Мой профиль", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="stats"),
               types.InlineKeyboardButton("🔗 Рефералка", callback_data="ref"))
    markup.add(types.InlineKeyboardButton("💎 PREMIUM (Купить)", callback_data="vip"))
    markup.add(types.InlineKeyboardButton("💬 Техподдержка", callback_data="support"))
    return markup

def get_back_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
    return markup

@bot.message_handler(commands=['start'])
def start_message(message):
    ref_id = None
    if len(message.text.split()) > 1:
        try: ref_id = int(message.text.split()[1])
        except Exception: pass
    if add_user(message.chat.id, ref_id) and ref_id:
        try: bot.send_message(ref_id, "🎉 По твоей ссылке зарегистрировался друг!")
        except Exception: pass
    bot.send_message(message.chat.id, "🟢 <b>Radar Bet | Сканер запущен</b>\n\n🔎 <i>Сканер анализирует линию в реальном времени. Ожидайте сигналов...</i>", parse_mode="HTML", reply_markup=get_main_markup())

def process_support_msg(message):
    if message.text.startswith('/'): return
    bot.send_message(ADMIN_ID, f"📩 <b>ОБРАЩЕНИЕ</b>\n👤 Юзер ID: <code>{message.chat.id}</code>\n\n💬 Текст: {message.text}", parse_mode="HTML")
    bot.send_message(message.chat.id, "✅ Вопрос отправлен админу.", reply_markup=get_main_markup())

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.data == "main_menu":
        bot.edit_message_text("🟢 <b>Radar Bet | Сканер запущен</b>\n\n🔎 <i>Сканер анализирует линию в реальном времени. Ожидайте сигналов...</i>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_main_markup())
    elif call.data == "profile":
        cursor.execute('SELECT status, vip_until FROM users WHERE user_id = ?', (call.message.chat.id,))
        res = cursor.fetchone()
        status_text = f"<b>VIP</b> (до {datetime.datetime.fromtimestamp(res[1]).strftime('%d.%m.%Y')})" if res and res[0].upper() == "VIP" and res[1] > 0 else "<b>FREE</b>"
        bot.edit_message_text(f"📱 <b>Профиль</b>\nID: <code>{call.message.chat.id}</code>\nСтатус: {status_text}", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_back_markup())
    elif call.data == "stats":
        cursor.execute('SELECT wins, losses FROM stats')
        wins, losses = cursor.fetchone()
        total = wins + losses
        winrate = int((wins / total) * 100) if total > 0 else 0
        bot.edit_message_text(f"📊 <b>Статистика алгоритма</b>\n\n✅ Успешных сигналов: {wins}\n❌ Минусов: {losses}\n🔥 Винрейт: {winrate}%", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_back_markup())
    elif call.data == "vip":
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        prices = [types.LabeledPrice(label='VIP на 1 неделю', amount=50)]
        bot.send_invoice(call.message.chat.id, title="💎 VIP-доступ", description="Оплата подписки на 7 дней.", invoice_payload="vip_subscription", provider_token="", currency="XTR", prices=prices, reply_markup=get_back_markup())
    elif call.data == "ref":
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={call.message.chat.id}"
        cursor.execute("SELECT referrals FROM users WHERE user_id=?", (call.message.chat.id,))
        res = cursor.fetchone()
        ref_count = res[0] if res else 0
        text = f"🔗 <b>Твоя реферальная система</b>\n\n<i>Нажми на ссылку ниже, чтобы скопировать её:</i>\n👉 <code>{ref_link}</code> 👈\n\n👥 Приглашено: <b>{ref_count} чел.</b>"
        markup = types.InlineKeyboardMarkup()
        share_url = f"https://t.me/share/url?url={ref_link}&text=Лови крутого бота для ставок - Radar Bet!"
        markup.add(types.InlineKeyboardButton("🚀 Поделиться с другом", url=share_url))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
    elif call.data == "support":
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        msg = bot.send_message(call.message.chat.id, "✍️ <b>Напишите ваш вопрос:</b>", parse_mode="HTML", reply_markup=get_back_markup())
        bot.register_next_step_handler(msg, process_support_msg)
        # ==========================================
# 4. ПРЕДМАТЧ И АРСЕНАЛ СТРАТЕГИЙ
# ==========================================
def send_prematch_signal(admin_call=False, admin_id=None):
    today = datetime.date.today().isoformat()
    try:
        res = requests.get(f"https://v3.football.api-sports.io/fixtures?date={today}", headers=HEADERS, verify=False, timeout=10)
        matches = res.json().get('response', [])
        top_leagues = [39, 140, 135, 78, 61, 2, 3, 253, 71] # Топ-лиги Европы + MLS + Бразилия
        valid_matches = [m for m in matches if m['fixture']['status']['short'] == 'NS' and m['league']['id'] in top_leagues]
        
        selected_match, pred_text, conf, best_odd = None, "", 0, 0.0
        
        # Анализируем первые 5 подходящих матчей, чтобы не сжечь лимит API
        for match in valid_matches[:5]:
            fix_id = match['fixture']['id']
            url_pred = f"https://v3.football.api-sports.io/predictions?fixture={fix_id}"
            pred_res = requests.get(url_pred, headers=HEADERS, verify=False, timeout=10).json()
            
            if not pred_res.get('response'): continue
            home_perc = int(pred_res['response'][0]['predictions']['percent']['home'].replace('%', ''))
            
            if home_perc >= 65:
                url_odds = f"https://v3.football.api-sports.io/odds?fixture={fix_id}"
                odds_res = requests.get(url_odds, headers=HEADERS, verify=False, timeout=10).json()
                if odds_res.get('response') and odds_res['response'][0].get('bookmakers'):
                    for b in odds_res['response'][0]['bookmakers'][0]['bets']:
                        if b['id'] == 1: # Match Winner
                            for val in b['values']:
                                if val['value'] == 'Home':
                                    odd = float(val['odd'])
                                    if 1.60 <= odd <= 1.85:
                                        selected_match, pred_text, conf, best_odd = match, pred_res['response'][0]['predictions']['advice'], home_perc, odd
                                        break
                        if selected_match: break
            if selected_match: break
            time.sleep(1)

        if selected_match:
            home = selected_match['teams']['home']['name']
            away = selected_match['teams']['away']['name']
            m_time = datetime.datetime.fromtimestamp(selected_match['fixture']['timestamp']).strftime('%H:%M')
            msg = (f"📋 <b>ПРЕДМАТЧЕВАЯ РЕКОМЕНДАЦИЯ</b>\n\n⚽ {home} — {away}\n🕒 Начало в {m_time}\n\n"
                   f"🎯 <b>Прогноз:</b> Победа 1 (П1)\n🔥 <b>Кэф:</b> {best_odd}\n"
                   f"📊 <b>Уверенность нейросети:</b> {conf}%\n\n💡 <i>Анализ: {pred_text}</i>")
            for u in get_all_users():
                try: bot.send_message(u[0], msg, parse_mode="HTML")
                except: pass
            if admin_call and admin_id: bot.send_message(admin_id, "✅ Предматч найден и разослан!")
        else:
            if admin_call and admin_id: bot.send_message(admin_id, "❌ На сегодня подходящих предматчей (65%+ и КФ ~1.7) в топ-лигах не найдено. Попробуй позже.")
    except Exception as e:
        if admin_call and admin_id: bot.send_message(admin_id, f"❌ Ошибка поиска: {e}")

@bot.message_handler(commands=['prematch'])
def manual_prematch(message):
    if message.chat.id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "⏳ Ищу подходящий предматчевый сигнал... Это займет секунд 10-15.")
        Thread(target=send_prematch_signal, args=(True, ADMIN_ID)).start()

def auto_prematch():
    while True:
        time.sleep(43200) # Авто-поиск каждые 12 часов
        send_prematch_signal()

def auto_scanner():
    while True:
        users = get_all_users()
        current_date = datetime.date.today().isoformat()
        try:
            res = requests.get("https://v3.football.api-sports.io/fixtures?live=all", headers=HEADERS, verify=False, timeout=10)
            matches = res.json().get('response', [])
            
            for match in matches:
                fixture_id = match['fixture']['id']
                minute = match['fixture']['status']['elapsed']
                home_team = match['teams']['home']['name']
                away_team = match['teams']['away']['name']
                goals_home = match['goals']['home']
                goals_away = match['goals']['away']
                goals_sum = goals_home + goals_away
                score = f"{goals_home}:{goals_away}"
                
                if minute is None or fixture_id in signaled_matches: continue
                time.sleep(1.5)

                url_stats = f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}"
                stat_res = requests.get(url_stats, headers=HEADERS, verify=False, timeout=10).json()
                if not stat_res.get('response') or len(stat_res['response']) < 2: continue
                    
                home_stats = stat_res['response'][0]['statistics']
                away_stats = stat_res['response'][1]['statistics']
                
                def get_val(stats_list, name):
                    for i in stats_list:
                        if i['type'] == name and i['value'] is not None: 
                            return int(str(i['value']).replace('%', ''))
                    return 0
                
                h_shots, a_shots = get_val(home_stats, "Shots on Goal"), get_val(away_stats, "Shots on Goal")
                h_attacks, a_attacks = get_val(home_stats, "Dangerous Attacks"), get_val(away_stats, "Dangerous Attacks")
                h_poss, a_poss = get_val(home_stats, "Ball Possession"), get_val(away_stats, "Ball Possession")
                h_corners, a_corners = get_val(home_stats, "Corner Kicks"), get_val(away_stats, "Corner Kicks")
                
                prediction, confidence, reason, bet_type, bet_val, target_value = None, 0, "", "", "", 0.0
                
                if 10 <= minute <= 25 and (h_shots + a_shots) >= 3 and (h_attacks + a_attacks) >= 30:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 78, "Слишком открытое начало матча.", "OU", "Over", goals_sum + 0.5
                elif 25 <= minute <= 40 and goals_sum == 0 and (h_shots + a_shots) <= 1 and (h_attacks + a_attacks) <= 40:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Тотал Меньше (ТМ) 1.5", 82, "Абсолютно пассивная игра обеих команд, нет моментов.", "OU", "Under", 1.5
                elif 35 <= minute < 45 and (h_shots + a_shots) >= 5 and (h_attacks + a_attacks) >= 45 and (h_corners + a_corners) >= 4:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 80, "Огромное давление на последних минутах тайма.", "OU", "Over", goals_sum + 0.5
                elif 35 <= minute <= 65 and goals_home == 0 and goals_away >= 1 and h_poss >= 60 and h_shots >= 4 and a_shots <= 2:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 1 (П1)", 85, "Команда 1 пропустила, но диктует игру. Контроль мяча.", "1X2", "Home", 0
                elif 35 <= minute <= 65 and goals_away == 0 and goals_home >= 1 and a_poss >= 60 and a_shots >= 4 and h_shots <= 2:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 2 (П2)", 85, "Команда 2 пропустила, но диктует игру. Контроль мяча.", "1X2", "Away", 0
                elif 65 <= minute <= 75 and goals_sum == 0 and h_poss >= 65 and h_shots >= 6 and a_shots <= 1:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 1 (П1)", 84, "Тотальное доминирование первой команды при 0:0. Гол назревает.", "1X2", "Home", 0
                elif 65 <= minute <= 75 and goals_sum == 0 and a_poss >= 65 and a_shots >= 6 and h_shots <= 1:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 2 (П2)", 84, "Тотальное доминирование второй команды при 0:0. Гол назревает.", "1X2", "Away", 0
                elif 60 <= minute <= 75 and (h_shots + a_shots) <= 2 and (h_attacks + a_attacks) < 70:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Меньше (ТМ) {goals_sum + 1.5}", 90, "Игра проходит строго в центре поля.", "OU", "Under", goals_sum + 1.5
                elif 60 <= minute <= 80 and (h_shots + a_shots) >= 10 and (h_corners + a_corners) >= 9:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 88, "Открытая перестрелка. Вратари в игре.", "OU", "Over", goals_sum + 0.5
                elif 70 <= minute <= 80 and goals_home == goals_away and goals_sum >= 2 and h_attacks >= 60 and a_attacks >= 60 and (h_shots + a_shots) >= 8:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 86, "Обе команды идут за победой при ничейном счете.", "OU", "Over", goals_sum + 0.5
                elif 75 <= minute <= 85 and ((h_attacks >= 80 and h_shots >= 7 and goals_home <= goals_away) or (a_attacks >= 80 and a_shots >= 7 and goals_away <= goals_home)):
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 82, "Колоссальный навал одной из команд под конец матча.", "OU", "Over", goals_sum + 0.5

                if prediction:
                    real_odd = 0.0
                    try:
                        url_odds = f"https://v3.football.api-sports.io/odds/live?fixture={fixture_id}"
                        odds_res = requests.get(url_odds, headers=HEADERS, verify=False, timeout=10).json()
                        if odds_res.get('response'):
                            live_bets = odds_res['response'][0]['odds']
                            for bet in live_bets:
                                if bet_type == "OU" and bet['id'] == 20:
                                    for val in bet['values']:
                                        if bet_val in val['value']: real_odd = float(val['odd'])
                                elif bet_type == "1X2" and bet['id'] == 1:
                                    for val in bet['values']:
                                        if bet_val in val['value']: real_odd = float(val['odd'])
                                if real_odd > 0: break
                    except Exception: pass
                    
                    if 1.40 <= real_odd <= 2.20:
                        signaled_matches.add(fixture_id)
                        cursor.execute('INSERT INTO tracked_bets_v2 (fixture_id, home_team, away_team, bet_type, bet_val, target_value, odd, prediction_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                                       (fixture_id, home_team, away_team, bet_type, bet_val, target_value, real_odd, prediction))
                        conn.commit()
                        
                        signal_text = (f"⚡️ <b>СИГНАЛ РАДАРА</b>\n⚽ {home_team} — {away_team} | {minute}' | Счёт: <b>{score}</b>\n\n"
                                       f"🎯 <b>Исход:</b> {prediction}\n🔥 <b>Лайв-кэф:</b> {real_odd}\n"
                                       f"📊 <b>Уверенность алгоритма:</b> {confidence}%\n\n💡 <i>Анализ: {reason}</i>")
                        teaser_text = f"🔒 <b>СИГНАЛ СКРЫТ</b>\nАлгоритм нашел ставку с вероятностью {confidence}% на матч <b>{home_team} — {away_team}</b>.\n⚠️ Оформи VIP!"

                        for user in users:
                            u_id, u_status = user[0], user[1]
                            cursor.execute("SELECT signals_today, last_signal_date FROM users WHERE user_id=?", (u_id,))
                            row = cursor.fetchone()
                            sig_today, last_date = (row[0], row[1]) if row else (0, "")
                            
                            if last_date != current_date:
                                sig_today, last_date = 0, current_date

                            if u_status == 'VIP':
                                try: bot.send_message(u_id, signal_text, parse_mode="HTML")
                                except Exception: pass
                            else:
                                if sig_today < 1:
                                    try: bot.send_message(u_id, signal_text, parse_mode="HTML")
                                    except Exception: pass
                                    cursor.execute("UPDATE users SET signals_today=1, last_signal_date=? WHERE user_id=?", (current_date, u_id))
                                    conn.commit()
                                elif sig_today == 1:
                                    try: bot.send_message(u_id, teaser_text, parse_mode="HTML")
                                    except Exception: pass
                                    cursor.execute("UPDATE users SET signals_today=2 WHERE user_id=?", (u_id,))
                                    conn.commit()
        except Exception: pass
        time.sleep(120) 

def result_checker():
    while True:
        time.sleep(600) 
        try:
            cursor.execute('SELECT fixture_id, home_team, away_team, bet_type, bet_val, target_value, odd, prediction_text FROM tracked_bets_v2')
            for f_id, h_team, a_team, b_type, b_val, t_val, odd, pred_txt in cursor.fetchall():
                url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                res = requests.get(url, headers=HEADERS, verify=False, timeout=10).json()
                if not res.get('response'): continue
                
                status = res['response'][0]['fixture']['status']['short']
                if status in ['FT', 'AET', 'PEN']:
                    f_home = res['response'][0]['goals']['home']
                    f_away = res['response'][0]['goals']['away']
                    f_goals = f_home + f_away
                    is_win = False
                    
                    if b_type == "OU":
                        if b_val == "Over" and f_goals > t_val: is_win = True
                        elif b_val == "Under" and f_goals < t_val: is_win = True
                    elif b_type == "1X2":
                        if b_val == "Home" and f_home > f_away: is_win = True
                        elif b_val == "Away" and f_away > f_home: is_win = True
                        elif b_val == "Draw" and f_home == f_away: is_win = True
                            
                    if is_win:
                        cursor.execute("UPDATE stats SET wins = wins + 1")
                        res_text = "✅ <b>СТАВКА ЗАШЛА!</b>"
                    else:
                        cursor.execute("UPDATE stats SET losses = losses + 1")
                        res_text = "❌ <b>МИНУС</b>"
                    
                    conn.commit()
                    cursor.execute("DELETE FROM tracked_bets_v2 WHERE fixture_id=?", (f_id,))
                    conn.commit()
                    
                    for u in get_all_users():
                        try: bot.send_message(u[0], f"{res_text}\n\n⚽ {h_team} — {a_team}\nИтог: <b>{f_home}:{f_away}</b>\nНаш прогноз: {pred_txt}\nКэф: {odd}", parse_mode="HTML")
                        except Exception: pass
        except Exception: pass

# ==========================================
# 5. FLASK СЕРВЕР (ДЛЯ ОБХОДА СНА RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/')
def keep_alive(): return "Radar is running 24/7!"
def run_flask(): app.run(host="0.0.0.0", port=10000)

if __name__ == '__main__':
    Thread(target=auto_prematch, daemon=True).start()
    Thread(target=auto_scanner, daemon=True).start()
    Thread(target=result_checker, daemon=True).start()
    Thread(target=run_flask, daemon=True).start()
    
    print("🚀 БОТ ЗАПУЩЕН НА RENDER!")
    while True:
        try: bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception: time.sleep(5)
        
