import os
import logging
import json
from datetime import datetime, date, timedelta, time
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID   = os.environ['CHAT_ID']
GCREDS    = os.environ['GOOGLE_CREDS']
SHEET_ID  = os.environ.get('SPREADSHEET_ID', '')
MSK       = ZoneInfo('Europe/Moscow')
DONE      = ('Завершено', 'Выполнено')

# emoji как правильные unicode
E_DINO   = '\U0001F995'  # 🦕
E_OK     = '\u2705'      # ✅
E_SPIN   = '\U0001F504'  # 🔄
E_RED    = '\U0001F534'  # 🔴
E_CIRC   = '\u2B55'      # ⭕
E_PIN    = '\U0001F4CC'  # 📌
E_CAL    = '\U0001F4C5'  # 📅
E_LINK   = '\U0001F517'  # 🔗
E_CHART  = '\U0001F4CA'  # 📊
E_CLOCK  = '\u23F1'      # ⏱
E_CLIP   = '\U0001F4CB'  # 📋
E_WARN   = '\u26A0\uFE0F' # ⚠️
E_MAP    = '\U0001F4CD'  # 📍
E_ORG    = '\U0001F7E0'  # 🟠
E_YEL    = '\U0001F7E1'  # 🟡


def sheets_client():
    d = json.loads(GCREDS)
    sc = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly',
    ]
    return gspread.authorize(Credentials.from_service_account_info(d, scopes=sc))


def get_tasks():
    try:
        ws = sheets_client().open_by_key(SHEET_ID).worksheet('WBS')
        result = []
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Название'):
                continue
            try:
                end = datetime.strptime(
                    str(r.get('Дата окончания', '')).strip(), '%d.%m.%Y'
                ).date()
            except Exception:
                continue
            result.append({
                'code':   str(r['Код']),
                'name':   str(r['Название']),
                'resp':   str(r.get('Ответственный', '')),
                'status': str(r.get('Статус', 'Не начато')),
                'end':    end,
            })
        return result
    except Exception as e:
        logger.error('WBS error: %s', e)
        return []


def get_milestones():
    try:
        ws = sheets_client().open_by_key(SHEET_ID).worksheet('Реестр КТ')
        result = []
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Контрольная точка'):
                continue
            try:
                d = datetime.strptime(
                    str(r.get('Плановая дата', '')).strip(), '%d.%m.%Y'
                ).date()
            except Exception:
                continue
            result.append({
                'code':   str(r['Код']),
                'name':   str(r['Контрольная точка']),
                'date':   d,
                'resp':   str(r.get('Ответственный', '')),
                'status': str(r.get('Статус', 'Не начато')),
                'crit':   str(r.get('Критичность', '')),
            })
        return result
    except Exception as e:
        logger.error('KT error: %s', e)
        return []


def se(s):
    return {
        'Завершено': E_OK, 'Выполнено': E_OK,
        'В работе': E_SPIN, 'Просрочено': E_RED,
    }.get(s, E_CIRC)


def ce(c):
    return {
        'Критическая': E_RED,
        'Высокая': E_ORG,
        'Средняя': E_YEL,
    }.get(c, '\u26AA')


def build_digest(tasks, milestones):
    today = date.today()
    week  = today + timedelta(days=7)
    overdue    = [t for t in tasks if t['end'] < today and t['status'] not in DONE]
    today_list = [t for t in tasks if t['end'] == today and t['status'] not in DONE]
    week_list  = [t for t in tasks if today < t['end'] <= week and t['status'] not in DONE]

    lines = [
        E_DINO + ' *ПМО Динозавры ' + today.strftime('%d.%m.%Y') + '*',
        '_Поставка 12 фигур SANHE -> ООО Парк Сказка_',
        '',
    ]
    if overdue:
        lines.append(E_RED + ' *ПРОСРОЧЕНО:*')
        for t in overdue[:5]:
            d = (today - t['end']).days
            lines.append('  `' + t['code'] + '` ' + t['name'][:40] + ' - ' + t['resp'] + ' *(+' + str(d) + 'дн)*')
        lines.append('')
    if today_list:
        lines.append(E_PIN + ' *Сегодня:*')
        for t in today_list[:8]:
            lines.append('  ' + se(t['status']) + ' `' + t['code'] + '` ' + t['name'][:40])
            lines.append('     - ' + t['resp'])
        lines.append('')
    else:
        lines.append(E_PIN + ' *Сегодня:* задач с дедлайном нет')
        lines.append('')
    if week_list:
        lines.append(E_CAL + ' *На 7 дней (' + str(len(week_list)) + ' задач):*')
        for t in sorted(week_list, key=lambda x: x['end'])[:8]:
            lines.append('  ' + E_CIRC + ' `' + t['code'] + '` ' + t['name'][:35] + ' - ' + t['end'].strftime('%d.%m'))
        lines.append('')
    lines.append(E_LINK + ' https://galkinva.github.io/pmo-dinosaurs/')
    return '\n'.join(lines)


def build_alert(milestones):
    today = date.today()
    up = []
    for m in milestones:
        if m['status'] in DONE:
            continue
        delta = (m['date'] - today).days
        if 0 <= delta <= 3:
            up.append((delta, m))
    if not up:
        return None
    lines = [E_WARN + ' *Приближающиеся вехи:*', '']
    for delta, m in sorted(up):
        if delta == 0:
            when = E_RED + ' *СЕГОДНЯ*'
        elif delta == 1:
            when = E_ORG + ' *Завтра*'
        else:
            when = E_YEL + ' Через ' + str(delta) + 'дн (' + m['date'].strftime('%d.%m') + ')'
        lines.append(ce(m['crit']) + ' `' + m['code'] + '` ' + m['name'][:45])
        lines.append('  - ' + when + ' - ' + m['resp'])
        lines.append('')
    return '\n'.join(lines)


def build_milestones(milestones):
    today = date.today()
    lines = [E_MAP + ' *Реестр контрольных точек:*', '']
    for m in milestones:
        delta = (m['date'] - today).days
        if m['status'] in DONE:
            mk, ti = E_OK, 'выполнено'
        elif delta < 0:
            mk, ti = E_RED, 'просрочено на ' + str(-delta) + 'дн'
        elif delta == 0:
            mk, ti = E_RED, 'СЕГОДНЯ'
        elif delta <= 3:
            mk, ti = E_ORG, 'через ' + str(delta) + 'дн'
        elif delta <= 7:
            mk, ti = E_YEL, 'через ' + str(delta) + 'дн'
        else:
            mk, ti = E_CIRC, m['date'].strftime('%d.%m.%Y')
        lines.append(mk + ' `' + m['code'] + '` ' + m['name'][:45])
        lines.append('  - ' + ti + ' - ' + m['resp'])
    return '\n'.join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        E_DINO + ' *PMO Bot - Парковая Инфраструктура*\n\n'
        '/status - статус проекта\n'
        '/tasks - задачи на 7 дней\n'
        '/milestones - все вехи\n\n'
        '- 09:00 МСК пн-пт - дайджест\n'
        '- 09:05 ежедневно - вехи за 3дн'
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    dl    = date(2026, 7, 28)
    tasks = get_tasks()
    done  = sum(1 for t in tasks if t['status'] in DONE)
    total = len(tasks)
    text = (
        E_CHART + ' *Статус проекта - ' + today.strftime('%d.%m.%Y') + '*\n\n'
        + E_CLOCK + ' До дедлайна: *' + str((dl - today).days) + ' дн.* (28.07.2026)\n'
        + E_CLIP + ' Выполнено: *' + str(done) + '/' + str(total) + '*\n\n'
        + E_LINK + ' https://galkinva.github.io/pmo-dinosaurs/'
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks()
    if not tasks:
        await update.message.reply_text(E_WARN + ' Не удалось загрузить задачи.')
        return
    await update.message.reply_text(build_digest(tasks, get_milestones()), parse_mode='Markdown')


async def cmd_milestones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ms = get_milestones()
    if not ms:
        await update.message.reply_text(E_WARN + ' Не удалось загрузить вехи.')
        return
    await update.message.reply_text(build_milestones(ms), parse_mode='Markdown')


async def job_morning(context: CallbackContext):
    if date.today().weekday() >= 5:
        return
    text = build_digest(get_tasks(), get_milestones())
    await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='Markdown')
    logger.info('Morning digest sent')


async def job_milestones(context: CallbackContext):
    text = build_alert(get_milestones())
    if text:
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='Markdown')
        logger.info('Milestone alert sent')


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start',      cmd_start))
    app.add_handler(CommandHandler('status',     cmd_status))
    app.add_handler(CommandHandler('tasks',      cmd_tasks))
    app.add_handler(CommandHandler('milestones', cmd_milestones))
    jq = app.job_queue
    jq.run_daily(job_morning,    time=time(9, 0, tzinfo=MSK))
    jq.run_daily(job_milestones, time=time(9, 5, tzinfo=MSK))
    logger.info('PMO Bot running...')
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
