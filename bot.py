import os, logging, asyncio, json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN   = os.environ['BOT_TOKEN']
CHAT_ID     = os.environ['CHAT_ID']
GCREDS      = os.environ['GOOGLE_CREDS']
SHEET_ID    = os.environ.get('SPREADSHEET_ID', '')
TZ          = ZoneInfo('Europe/Moscow')

def sheets():
    d = json.loads(GCREDS)
    sc = ['https://www.googleapis.com/auth/spreadsheets.readonly',
          'https://www.googleapis.com/auth/drive.readonly']
    return gspread.authorize(Credentials.from_service_account_info(d, scopes=sc))

def get_tasks():
    try:
        ws = sheets().open_by_key(SHEET_ID).worksheet('WBS')
        out = []
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Название'):
                continue
            try:
                end = datetime.strptime(str(r.get('Дата окончания', '')).strip(), '%d.%m.%Y').date()
            except Exception:
                continue
            out.append({
                'code': str(r['Код']),
                'name': str(r['Название']),
                'resp': str(r.get('Ответственный', '')),
                'status': str(r.get('Статус', 'Не начато')),
                'end': end,
            })
        return out
    except Exception as e:
        logger.error('WBS: %s', e)
        return []

def get_milestones():
    try:
        ws = sheets().open_by_key(SHEET_ID).worksheet('Реестр КТ')
        out = []
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Контрольная точка'):
                continue
            try:
                d = datetime.strptime(str(r.get('Плановая дата', '')).strip(), '%d.%m.%Y').date()
            except Exception:
                continue
            out.append({
                'code': str(r['Код']),
                'name': str(r['Контрольная точка']),
                'date': d,
                'resp': str(r.get('Ответственный', '')),
                'status': str(r.get('Статус', 'Не начато')),
                'crit': str(r.get('Критичность', '')),
            })
        return out
    except Exception as e:
        logger.error('KT: %s', e)
        return []

DONE = ('Завершено', 'Выполнено')

def se(s):
    return {'\u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e': '\u2705',
            '\u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e': '\u2705',
            '\u0412 \u0440\u0430\u0431\u043e\u0442\u0435': '\ud83d\udd04',
            '\u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043e': '\ud83d\udd34'}.get(s, '\u2b55')

def ce(c):
    return {'\u041a\u0440\u0438\u0442\u0438\u0447\u0435\u0441\u043a\u0430\u044f': '\ud83d\udd34',
            '\u0412\u044b\u0441\u043e\u043a\u0430\u044f': '\ud83d\udfe0',
            '\u0421\u0440\u0435\u0434\u043d\u044f\u044f': '\ud83d\udfe1'}.get(c, '\u26aa')

def digest(tasks, ms):
    t = date.today()
    w = t + timedelta(days=7)
    td = [x for x in tasks if x['end'] == t and x['status'] not in DONE]
    ov = [x for x in tasks if x['end'] < t and x['status'] not in DONE]
    wk = [x for x in tasks if t < x['end'] <= w and x['status'] not in DONE]
    lines = [
        '\ud83e\udd95 *\u041f\u041c\u041e \u0414\u0438\u043d\u043e\u0437\u0430\u0432\u0440\u044b \u00b7 ' + t.strftime('%d.%m.%Y') + '*',
        '_\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 12 \u0444\u0438\u0433\u0443\u0440 SANHE \u2192 \u041e\u041e\u041e \u00ab\u041f\u0430\u0440\u043a \u0421\u043a\u0430\u0437\u043a\u0430\u00bb_',
        '',
    ]
    if ov:
        lines.append('\ud83d\udd34 *\u041f\u0420\u041e\u0421\u0420\u041e\u0427\u0415\u041d\u041e:*')
        for x in ov[:5]:
            lines.append('  `' + x['code'] + '` ' + x['name'][:40] + ' \u2014 ' + x['resp'] + ' *(+' + str((t - x['end']).days) + '\u0434\u043d)*')
        lines.append('')
    if td:
        lines.append('\ud83d\udccc *\u0421\u0435\u0433\u043e\u0434\u043d\u044f:*')
        for x in td[:8]:
            lines.append('  ' + se(x['status']) + ' `' + x['code'] + '` ' + x['name'][:40])
            lines.append('     \u2514 ' + x['resp'])
        lines.append('')
    else:
        lines.append('\ud83d\udccc *\u0421\u0435\u0433\u043e\u0434\u043d\u044f:* \u0437\u0430\u0434\u0430\u0447 \u0441 \u0434\u0435\u0434\u043b\u0430\u0439\u043d\u043e\u043c \u043d\u0435\u0442')
        lines.append('')
    if wk:
        lines.append('\ud83d\udcc5 *\u041d\u0430 7 \u0434\u043d\u0435\u0439 (' + str(len(wk)) + ' \u0437\u0430\u0434\u0430\u0447):*')
        for x in sorted(wk, key=lambda x: x['end'])[:8]:
            lines.append('  \u2b55 `' + x['code'] + '` ' + x['name'][:35] + ' \u2014 ' + x['end'].strftime('%d.%m'))
        lines.append('')
    lines.append('\ud83d\udd17 https://galkinva.github.io/pmo-dinosaurs/')
    return '\n'.join(lines)

def milestone_alert(ms):
    t = date.today()
    up = []
    for m in ms:
        if m['status'] in DONE:
            continue
        delta = (m['date'] - t).days
        if 0 <= delta <= 3:
            up.append((delta, m))
    if not up:
        return None
    lines = ['\u26a0\ufe0f *\u041f\u0440\u0438\u0431\u043b\u0438\u0436\u0430\u044e\u0449\u0438\u0435\u0441\u044f \u0432\u0435\u0445\u0438:*', '']
    for delta, m in sorted(up):
        if delta == 0:
            when = '\ud83d\udd34 *\u0421\u0415\u0413\u041e\u0414\u041d\u042f*'
        elif delta == 1:
            when = '\ud83d\udfe0 *\u0417\u0430\u0432\u0442\u0440\u0430*'
        else:
            when = '\ud83d\udfe1 \u0427\u0435\u0440\u0435\u0437 ' + str(delta) + '\u0434\u043d (' + m['date'].strftime('%d.%m') + ')'
        lines.append(ce(m['crit']) + ' `' + m['code'] + '` ' + m['name'][:45])
        lines.append('  \u2514 ' + when + ' \u00b7 ' + m['resp'])
        lines.append('')
    return '\n'.join(lines)

def all_milestones(ms):
    t = date.today()
    lines = ['\ud83d\udccd *\u0420\u0435\u0435\u0441\u0442\u0440 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c\u043d\u044b\u0445 \u0442\u043e\u0447\u0435\u043a:*', '']
    for m in ms:
        delta = (m['date'] - t).days
        if m['status'] in DONE:
            mk, ti = '\u2705', '\u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e'
        elif delta < 0:
            mk, ti = '\ud83d\udd34', '\u043f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043e \u043d\u0430 ' + str(-delta) + '\u0434\u043d'
        elif delta == 0:
            mk, ti = '\ud83d\udd34', '\u0421\u0415\u0413\u041e\u0414\u041d\u042f'
        elif delta <= 3:
            mk, ti = '\ud83d\udfe0', '\u0447\u0435\u0440\u0435\u0437 ' + str(delta) + '\u0434\u043d'
        elif delta <= 7:
            mk, ti = '\ud83d\udfe1', '\u0447\u0435\u0440\u0435\u0437 ' + str(delta) + '\u0434\u043d'
        else:
            mk, ti = '\u2b55', m['date'].strftime('%d.%m.%Y')
        lines.append(mk + ' `' + m['code'] + '` ' + m['name'][:45])
        lines.append('  \u2514 ' + ti + ' \u00b7 ' + m['resp'])
    return '\n'.join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        '\ud83e\udd95 *PMO Bot \u2014 \u041f\u0430\u0440\u043a\u043e\u0432\u0430\u044f \u0418\u043d\u0444\u0440\u0430\u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0430*\n\n'
        '/status \u2014 \u0441\u0442\u0430\u0442\u0443\u0441 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\n'
        '/tasks \u2014 \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0430 7 \u0434\u043d\u0435\u0439\n'
        '/milestones \u2014 \u0432\u0441\u0435 \u0432\u0435\u0445\u0438\n\n'
        '\u2022 09:00 \u041c\u0421\u041a \u043f\u043d\u2013\u043f\u0442 \u2014 \u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442\n'
        '\u2022 09:05 \u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e \u2014 \u0432\u0435\u0445\u0438 \u0437\u0430 3\u0434\u043d'
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = date.today()
    dl = date(2026, 7, 28)
    tasks = get_tasks()
    done = sum(1 for x in tasks if x['status'] in DONE)
    total = len(tasks)
    text = (
        '\ud83d\udcca *\u0421\u0442\u0430\u0442\u0443\u0441 \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u00b7 ' + t.strftime('%d.%m.%Y') + '*\n\n'
        '\u23f1 \u0414\u043e \u0434\u0435\u0434\u043b\u0430\u0439\u043d\u0430: *' + str((dl - t).days) + ' \u0434\u043d.* (28.07.2026)\n'
        '\ud83d\udccb \u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e: *' + str(done) + '/' + str(total) + '*\n\n'
        '\ud83d\udd17 https://galkinva.github.io/pmo-dinosaurs/'
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks()
    if not tasks:
        await update.message.reply_text('\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0437\u0430\u0434\u0430\u0447\u0438.')
        return
    await update.message.reply_text(digest(tasks, get_milestones()), parse_mode='Markdown')


async def cmd_milestones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ms = get_milestones()
    if not ms:
        await update.message.reply_text('\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0432\u0435\u0445\u0438.')
        return
    await update.message.reply_text(all_milestones(ms), parse_mode='Markdown')


async def job_digest(bot):
    if date.today().weekday() >= 5:
        return
    await bot.send_message(chat_id=CHAT_ID, text=digest(get_tasks(), get_milestones()), parse_mode='Markdown')


async def job_alert(bot):
    text = milestone_alert(get_milestones())
    if text:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='Markdown')


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('tasks', cmd_tasks))
    app.add_handler(CommandHandler('milestones', cmd_milestones))
    sch = AsyncIOScheduler(timezone=TZ)
    sch.add_job(lambda: asyncio.create_task(job_digest(app.bot)), 'cron', hour=9, minute=0)
    sch.add_job(lambda: asyncio.create_task(job_alert(app.bot)), 'cron', hour=9, minute=5)
    sch.start()
    logger.info('PMO Bot running...')
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
