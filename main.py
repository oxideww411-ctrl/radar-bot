import telebot
from telebot import types
import requests
import time
import threading
import datetime
from flask import Flask
from threading import Thread
import psycopg2

TOKEN = "8704937440:AAE2giwzq-9eFPT0FrwTJ4ApuetW5HuC7pI"
ADMIN_ID = 1682561630 

API_KEYS = [
    "3346c861411945f05ce3135adee75c6b",
    "e2d74bb246da1059943a02c62dbd849d",
    "6872be91ea6a61ff3c3540252c05b4dc",
    "c73b37b026e747d7aa4efa55e751cc69"
]
current_key_idx = 0

bot = telebot.TeleBot(TOKEN)
signaled_matches = set()

# ТВОЯ ОБЛАЧНАЯ БАЗА NEON
DB_URL = "postgresql://neondb_owner:npg_ZJ3M4mjrHDTc@ep-cold-voice-av6zk9ax-pooler.c-11.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def fetch_api(url):
    global current_key_idx
    for _ in range(len(API_KEYS)):
        headers = {'x-apisports-key': API_KEYS[current_key_idx]}
        try:
            res = requests.get(url, headers=headers, verify=False, timeout=10).json()
            if res.get('errors'):
                errs = res['errors']
                if (isinstance(errs, dict) and ('requests' in errs or 'rateLimit' in errs)) or (isinstance(errs, list) and any('limit' in str(e).lower() for e in errs)):
                    current_key_idx = (current_key_idx + 1) % len(API_KEYS)
                    continue
            return res
        except Exception:
            pass
    return {}

# ==========================================
# 1. ОБЛАЧНАЯ БАЗА ДАННЫХ (POSTGRESQL)
# ==========================================
def execute_query(query, params=None, fetch=False, fetchall=False):
    try:
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = None
        if fetch: result = cursor.fetchone()
        elif fetchall: result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        print("DB Error:", e)
        return None

execute_query('CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, status TEXT)')
try:
    execute_query("ALTER TABLE users ADD COLUMN signals_today INTEGER DEFAULT 0")
    execute_query("ALTER TABLE users ADD COLUMN last_signal_date TEXT DEFAULT ''")
    execute_query("ALTER TABLE users ADD COLUMN vip_until BIGINT DEFAULT 0")
    execute_query("ALTER TABLE users ADD COLUMN referrals INTEGER DEFAULT 0")
except: pass

execute_query('CREATE TABLE IF NOT EXISTS stats (wins INTEGER, losses INTEGER)')
if not execute_query('SELECT * FROM stats', fetch=True):
    execute_query('INSERT INTO stats (wins, losses) VALUES (0, 0)')

execute_query('''CREATE TABLE IF NOT EXISTS tracked_bets_v2 (
    fixture_id BIGINT, home_team TEXT, away_team TEXT, bet_type TEXT, bet_val TEXT, target_value REAL, odd REAL, prediction_text TEXT)''')

def add_user(user_id, ref_id=None):
    if not execute_query('SELECT * FROM users WHERE user_id=%s', (user_id,), fetch=True):
        execute_query("INSERT INTO users (user_id, status, signals_today, last_signal_date, vip_until, referrals) VALUES (%s, 'free', 0, '', 0, 0)", (user_id,))
        if ref_id and ref_id != user_id:
            execute_query("UPDATE users SET referrals = referrals + 1 WHERE user_id=%s", (ref_id,))
            return True
    return False

def get_all_users():
    execute_query("UPDATE users SET status='FREE' WHERE status='VIP' AND vip_until > 0 AND vip_until < %s", (int(time.time()),))
    return execute_query('SELECT user_id, status FROM users', fetchall=True) or []

# ==========================================
# 2. ПРИЕМ ОПЛАТЫ И АДМИНКА
# ==========================================
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query): bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    user_id = message.chat.id
    expire_time = int(time.time()) + (7 * 24 * 3600)
    execute_query("UPDATE users SET status='VIP', vip_until=%s WHERE user_id=%s", (expire_time, user_id))
    bot.send_message(user_id, "✅ <b>Оплата прошла успешно!</b>\n\n💎 VIP-доступ на <b>1 неделю</b> активирован.", parse_mode="HTML")
    bot.send_message(ADMIN_ID, f"💰 <b>НОВАЯ ОПЛАТА! 50 Stars</b>\nПользователь <code>{user_id}</code> купил подписку!")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id == ADMIN_ID:
        total = execute_query('SELECT COUNT(*) FROM users', fetch=True)
        vips = execute_query("SELECT COUNT(*) FROM users WHERE status='VIP'", fetch=True)
        stats = execute_query('SELECT wins, losses FROM stats', fetch=True)
        t_count = total[0] if total else 0
        v_count = vips[0] if vips else 0
        w_count, l_count = stats if stats else (0,0)
        bot.send_message(message.chat.id, f"👑 <b>ПАНЕЛЬ СОЗДАТЕЛЯ (Облако активна)</b>\n\n👥 Клиентов: {t_count} (VIP: {v_count})\n✅ Плюсов: {w_count} | ❌ Минусов: {l_count}\n🔑 Текущий API ключ: #{current_key_idx+1}\n\nВыдать VIP: <code>/addvip [ID]</code>\nРассылка: <code>/send [текст]</code>\nПредматч: <code>/prematch</code>\nБэкап: <code>/backup</code>", parse_mode="HTML")

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        stats = execute_query('SELECT wins, losses FROM stats', fetch=True) or (0,0)
        users = execute_query('SELECT user_id, status FROM users', fetchall=True) or []
        text = f"☁️ <b>БАЗА В БЕЗОПАСНОСТИ (Neon)</b>\nФайл больше не нужен, данные в облаке!\n\nСтатистика: Плюсы {stats[0]} | Минусы {stats[1]}\nВсего юзеров: {len(users)}\n"
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")

@bot.message_handler(commands=['addvip'])
def give_vip(message):
    if message.chat.id == ADMIN_ID:
        try:
            user_id = int(message.text.split()[1])
            expire_time = int(time.time()) + (7 * 24 * 3600)
            execute_query("UPDATE users SET status='VIP', vip_until=%s WHERE user_id=%s", (expire_time, user_id))
            bot.send_message(ADMIN_ID, f"✅ VIP выдан {user_id}!")
        except: pass

@bot.message_handler(commands=['send'])
def broadcast_message(message):
    if message.chat.id == ADMIN_ID:
        text = message.text.replace("/send", "").strip()
        if text:
            for u in get_all_users():
                try: bot.send_message(u[0], text)
                except: pass
            bot.send_message(ADMIN_ID, "✅ Рассылка завершена.")

@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID and message.reply_to_message is not None)
def admin_reply_to_user(message):
    try:
        user_id = int(message.reply_to_message.text.split("Юзер ID: ")[1].split("\n")[0].strip())
        bot.send_message(user_id, f"👨‍💻 <b>Ответ от Поддержки:</b>\n\n{message.text}", parse_mode="HTML")
        bot.reply_to(message, "✅ Отправлено!")
    except: pass

# ==========================================
# 3. МЕНЮ
# ==========================================
def get_main_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Мой профиль", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="stats"), types.InlineKeyboardButton("🔗 Рефералка", callback_data="ref"))
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
        except: pass
    if add_user(message.chat.id, ref_id) and ref_id:
        try: bot.send_message(ref_id, "🎉 По твоей ссылке зарегистрировался друг!")
        except: pass
    bot.send_message(message.chat.id, "🟢 <b>Radar Bet | Сканер запущен</b>\n\n🔎 <i>ИИ сканирует линию по Индексу Давления в реальном времени. Ожидайте сигналов...</i>", parse_mode="HTML", reply_markup=get_main_markup())

def process_support_msg(message):
    if message.text.startswith('/'): return
    bot.send_message(ADMIN_ID, f"📩 <b>ОБРАЩЕНИЕ</b>\n👤 Юзер ID: <code>{message.chat.id}</code>\n\n💬 {message.text}", parse_mode="HTML")
    bot.send_message(message.chat.id, "✅ Вопрос отправлен админу.", reply_markup=get_main_markup())

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.data == "main_menu":
        bot.edit_message_text("🟢 <b>Radar Bet | Сканер запущен</b>\n\n🔎 <i>ИИ сканирует линию по Индексу Давления в реальном времени...</i>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_main_markup())
    elif call.data == "profile":
        res = execute_query('SELECT status, vip_until FROM users WHERE user_id = %s', (call.message.chat.id,), fetch=True)
        status_text = f"<b>VIP</b> (до {datetime.datetime.fromtimestamp(res[1]).strftime('%d.%m.%Y')})" if res and res[0].upper() == "VIP" and res[1] > 0 else "<b>FREE</b>"
        bot.edit_message_text(f"📱 <b>Профиль</b>\nID: <code>{call.message.chat.id}</code>\nСтатус: {status_text}", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_back_markup())
    elif call.data == "stats":
        stats = execute_query('SELECT wins, losses FROM stats', fetch=True)
        wins, losses = stats if stats else (0,0)
        winrate = int((wins / (wins + losses)) * 100) if (wins + losses) > 0 else 0
        bot.edit_message_text(f"📊 <b>Статистика алгоритма</b>\n\n✅ Успешных сигналов: {wins}\n❌ Минусов: {losses}\n🔥 Винрейт: {winrate}%", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=get_back_markup())
    elif call.data == "vip":
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        try:
            prices = [types.LabeledPrice(label='VIP на 1 неделю', amount=50)]
            bot.send_invoice(
                call.message.chat.id, 
                title="💎 VIP-доступ", 
                description="Оплата подписки на 7 дней.", 
                invoice_payload="vip", 
                provider_token="", 
                currency="XTR", 
                prices=prices, 
                reply_markup=get_back_markup()
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ <b>Ошибка кассы:</b> {e}", parse_mode="HTML", reply_markup=get_back_markup())
    elif call.data == "ref":
        ref_link = f"https://t.me/{bot.get_me().username}?start={call.message.chat.id}"
        res = execute_query("SELECT referrals FROM users WHERE user_id=%s", (call.message.chat.id,), fetch=True)
        ref_count = res[0] if res else 0
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚀 Поделиться с другом", url=f"https://t.me/share/url?url={ref_link}&text=Лови крутого бота для ставок - Radar Bet!"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
        bot.edit_message_text(f"🔗 <b>Твоя реферальная система</b>\n\n<i>Нажми на ссылку ниже, чтобы скопировать её:</i>\n👉 <code>{ref_link}</code> 👈\n\n👥 Приглашено: <b>{ref_count} чел.</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=markup)
    elif call.data == "support":
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        msg = bot.send_message(call.message.chat.id, "✍️ <b>Напишите ваш вопрос:</b>", parse_mode="HTML", reply_markup=get_back_markup())
        bot.register_next_step_handler(msg, process_support_msg)
        # ==========================================
# 4. ИНДЕКС ДАВЛЕНИЯ И ВАЛУЙ ПРЕДМАТЧ
# ==========================================
def send_prematch_signal(admin_call=False, admin_id=None):
    today = datetime.date.today().isoformat()
    try:
        res = fetch_api(f"https://v3.football.api-sports.io/fixtures?date={today}")
        matches = res.get('response', [])
        # Добавили Лигу Чемпионов (2), Лигу Европы (3) и Женскую ЛЧ (132)
        top_leagues = [39, 140, 135, 78, 61, 2, 3, 253, 71, 4, 5, 9, 15, 132] 
        valid_matches = [m for m in matches if m['fixture']['status']['short'] == 'NS' and m['league']['id'] in top_leagues]
        
        selected_match, pred_text, conf, best_odd = None, "", 0, 0.0
        
        for match in valid_matches[:5]:
            fix_id = match['fixture']['id']
            pred_res = fetch_api(f"https://v3.football.api-sports.io/predictions?fixture={fix_id}")
            if not pred_res.get('response'): continue
            home_perc = int(pred_res['response'][0]['predictions']['percent']['home'].replace('%', ''))
            
            if home_perc >= 60:
                expected_odd = 1 / (home_perc / 100)
                odds_res = fetch_api(f"https://v3.football.api-sports.io/odds?fixture={fix_id}")
                if odds_res.get('response') and odds_res['response'][0].get('bookmakers'):
                    for b in odds_res['response'][0]['bookmakers'][0]['bets']:
                        if b['id'] == 1: 
                            for val in b['values']:
                                if val['value'] == 'Home':
                                    odd = float(val['odd'])
                                    if 1.60 <= odd <= 1.95 and odd >= (expected_odd * 1.05):
                                        selected_match, pred_text, conf, best_odd = match, pred_res['response'][0]['predictions']['advice'], home_perc, odd
                                        break
                        if selected_match: break
            if selected_match: break
            time.sleep(1)

        if selected_match:
            home, away = selected_match['teams']['home']['name'], selected_match['teams']['away']['name']
            m_time = datetime.datetime.fromtimestamp(selected_match['fixture']['timestamp']).strftime('%H:%M')
            msg = f"📋 <b>ПРЕДМАТЧ | ВАЛУЙ НАЙДЕН</b>\n\n⚽ {home} — {away}\n🕒 Начало в {m_time}\n\n🎯 <b>Прогноз:</b> Победа 1 (П1)\n🔥 <b>Кэф:</b> {best_odd}\n📊 <b>Уверенность ИИ:</b> {conf}%\n\n💡 <i>Алгоритм выявил недооцененный коэффициент. {pred_text}</i>"
            for u in get_all_users():
                try: bot.send_message(u[0], msg, parse_mode="HTML")
                except: pass
            if admin_call and admin_id: bot.send_message(admin_id, "✅ Валуй найден и разослан!")
        else:
            if admin_call and admin_id: bot.send_message(admin_id, "❌ Валуйных кэфов в топ-лигах пока нет.")
    except Exception as e:
        if admin_call and admin_id: bot.send_message(admin_id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['prematch'])
def manual_prematch(message):
    if message.chat.id == ADMIN_ID:
        bot.send_message(ADMIN_ID, "⏳ Ищу валуйный предматчевый сигнал...")
        Thread(target=send_prematch_signal, args=(True, ADMIN_ID)).start()

def auto_prematch():
    while True:
        time.sleep(43200)
        send_prematch_signal()

def auto_scanner():
    while True:
        users = get_all_users()
        current_date = datetime.date.today().isoformat()
        try:
            res = fetch_api("https://v3.football.api-sports.io/fixtures?live=all")
            matches = res.get('response', [])
            
            for match in matches:
                fixture_id = match['fixture']['id']
                minute = match['fixture']['status']['elapsed']
                home_team, away_team = match['teams']['home']['name'], match['teams']['away']['name']
                goals_home, goals_away = match['goals']['home'], match['goals']['away']
                goals_sum = goals_home + goals_away
                score = f"{goals_home}:{goals_away}"
                
                if minute is None or fixture_id in signaled_matches: continue
                if not ((15 <= minute <= 45) or (60 <= minute <= 85)): continue

                time.sleep(1)
                stat_res = fetch_api(f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}")
                if not stat_res.get('response') or len(stat_res['response']) < 2: continue
                    
                home_stats = stat_res['response'][0]['statistics']
                away_stats = stat_res['response'][1]['statistics']
                
                def get_val(stats_list, name):
                    for i in stats_list:
                        if i['type'] == name and i['value'] is not None: return int(str(i['value']).replace('%', ''))
                    return 0
                
                h_pi = (get_val(home_stats, "Dangerous Attacks") * 1.2) + (get_val(home_stats, "Shots on Goal") * 4) + (get_val(home_stats, "Corner Kicks") * 2.5)
                a_pi = (get_val(away_stats, "Dangerous Attacks") * 1.2) + (get_val(away_stats, "Shots on Goal") * 4) + (get_val(away_stats, "Corner Kicks") * 2.5)
                
                prediction, confidence, reason, bet_type, bet_val, target_value = None, 0, "", "", "", 0.0
                
                if 25 <= minute <= 40 and goals_sum == 0 and (h_pi + a_pi) < 45:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Тотал Меньше (ТМ) 1.5", 85, f"Мертвая игра. Индекс давления команд минимальный ({int(h_pi+a_pi)}).", "OU", "Under", 1.5
                elif 60 <= minute <= 80 and h_pi >= 70 and a_pi >= 70 and goals_sum >= 1:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 88, f"Острый футбол, открытая игра. Высокий индекс давления обеих команд.", "OU", "Over", goals_sum + 0.5
                elif 60 <= minute <= 80 and goals_home <= goals_away and h_pi > (a_pi + 50) and h_pi >= 85:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 1 (П1)", 86, f"Тотальный навал! Индекс давления {int(h_pi)} против {int(a_pi)}.", "1X2", "Home", 0
                elif 60 <= minute <= 80 and goals_away <= goals_home and a_pi > (h_pi + 50) and a_pi >= 85:
                    prediction, confidence, reason, bet_type, bet_val, target_value = "Победа 2 (П2)", 86, f"Тотальный навал! Индекс давления {int(a_pi)} против {int(h_pi)}.", "1X2", "Away", 0
                elif 15 <= minute <= 35 and (h_pi + a_pi) >= 95:
                    prediction, confidence, reason, bet_type, bet_val, target_value = f"Тотал Больше (ТБ) {goals_sum + 0.5}", 82, f"Безумный темп игры со старта. Высокий индекс давления.", "OU", "Over", goals_sum + 0.5

                if prediction:
                    real_odd = 0.0
                    try:
                        odds_res = fetch_api(f"https://v3.football.api-sports.io/odds/live?fixture={fixture_id}")
                        if odds_res.get('response'):
                            for bet in odds_res['response'][0]['odds']:
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
                        execute_query('INSERT INTO tracked_bets_v2 (fixture_id, home_team, away_team, bet_type, bet_val, target_value, odd, prediction_text) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', 
                                       (fixture_id, home_team, away_team, bet_type, bet_val, target_value, real_odd, prediction))
                        
                        signal_text = f"⚡️ <b>СИГНАЛ РАДАРА</b>\n⚽ {home_team} — {away_team} | {minute}' | Счёт: <b>{score}</b>\n\n🎯 <b>Исход:</b> {prediction}\n🔥 <b>Лайв-кэф:</b> {real_odd}\n📊 <b>Уверенность ИИ:</b> {confidence}%\n\n💡 <i>Анализ: {reason}</i>"
                        teaser_text = f"🔒 <b>СИГНАЛ СКРЫТ</b>\nАлгоритм нашел ставку с вероятностью {confidence}% на матч <b>{home_team} — {away_team}</b>.\n⚠️ Оформи VIP!"

                        for user in users:
                            u_id, u_status = user[0], user[1]
                            row = execute_query("SELECT signals_today, last_signal_date FROM users WHERE user_id=%s", (u_id,), fetch=True)
                            sig_today, last_date = (row[0], row[1]) if row else (0, "")
                            if last_date != current_date: sig_today, last_date = 0, current_date

                            if u_status == 'VIP':
                                try: bot.send_message(u_id, signal_text, parse_mode="HTML")
                                except: pass
                            else:
                                if sig_today < 1:
                                    try: bot.send_message(u_id, signal_text, parse_mode="HTML")
                                    except: pass
                                    execute_query("UPDATE users SET signals_today=1, last_signal_date=%s WHERE user_id=%s", (current_date, u_id))
                                elif sig_today == 1:
                                    try: bot.send_message(u_id, teaser_text, parse_mode="HTML")
                                    except: pass
                                    execute_query("UPDATE users SET signals_today=2 WHERE user_id=%s", (u_id,))
        except Exception: pass
        time.sleep(150) 

def result_checker():
    while True:
        time.sleep(600) 
        try:
            bets = execute_query('SELECT fixture_id, home_team, away_team, bet_type, bet_val, target_value, odd, prediction_text FROM tracked_bets_v2', fetchall=True)
            if not bets: continue 
            
            for f_id, h_team, a_team, b_type, b_val, t_val, odd, pred_txt in bets:
                res = fetch_api(f"https://v3.football.api-sports.io/fixtures?id={f_id}")
                if not res.get('response'): continue
                
                status = res['response'][0]['fixture']['status']['short']
                if status in ['FT', 'AET', 'PEN']:
                    f_home, f_away = res['response'][0]['goals']['home'], res['response'][0]['goals']['away']
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
                        execute_query("UPDATE stats SET wins = wins + 1")
                        res_text = "✅ <b>СТАВКА ЗАШЛА!</b>"
                    else:
                        execute_query("UPDATE stats SET losses = losses + 1")
                        res_text = "❌ <b>МИНУС</b>"
                    
                    execute_query("DELETE FROM tracked_bets_v2 WHERE fixture_id=%s", (f_id,))
                    
                    for u in get_all_users():
                        try: bot.send_message(u[0], f"{res_text}\n\n⚽ {h_team} — {a_team}\nИтог: <b>{f_home}:{f_away}</b>\nНаш прогноз: {pred_txt}\nКэф: {odd}", parse_mode="HTML")
                        except: pass
        except Exception: pass

# ==========================================
# 5. СЕРВЕР RENDER
# ==========================================
app = Flask(__name__)
@app.route('/')
def keep_alive(): return "Radar is running on Cloud DB!"
def run_flask(): app.run(host="0.0.0.0", port=10000)

if __name__ == '__main__':
    Thread(target=auto_prematch, daemon=True).start()
    Thread(target=auto_scanner, daemon=True).start()
    Thread(target=result_checker, daemon=True).start()
    Thread(target=run_flask, daemon=True).start()
    
    print("🚀 БОТ ЗАПУЩЕН! ОБЛАКО АКТИВНО")
    while True:
        try: bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception: time.sleep(5)
                           
