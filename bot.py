import os, logging, asyncio, json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(format='%(asctime)s-%(name)s-%(levelname)s-%(message)s',level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.environ['BOT_TOKEN']
CHAT_ID      = os.environ['CHAT_ID']
GOOGLE_CREDS = os.environ['GOOGLE_CREDS']
SPREADSHEET  = os.environ.get('SPREADSHEET_ID','')
TZ           = ZoneInfo('Europe/Moscow')

def get_sheets_client():
    d=json.loads(GOOGLE_CREDS)
    sc=['https://www.googleapis.com/auth/spreadsheets.readonly','https://www.googleapis.com/auth/drive.readonly']
    return gspread.authorize(Credentials.from_service_account_info(d,scopes=sc))

def get_tasks():
    try:
        ws=get_sheets_client().open_by_key(SPREADSHEET).worksheet('WBS')
        tasks=[]
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Название'): continue
            try: d=datetime.strptime(str(r.get('Дата окончания','')).strip(),'%d.%m.%Y').date()
            except: continue
            tasks.append({'code':str(r['Код']),'name':str(r['Название']),'resp':str(r.get('Ответственный','')),'status':str(r.get('Статус','Не начато')),'end':d})
        return tasks
    except Exception as e:
        logger.error(f'WBS error: {e}'); return []

def get_milestones():
    try:
        ws=get_sheets_client().open_by_key(SPREADSHEET).worksheet('Реестр КТ')
        ms=[]
        for r in ws.get_all_records():
            if not r.get('Код') or not r.get('Контрольная точка'): continue
            try: d=datetime.strptime(str(r.get('Плановая дата','')).strip(),'%d.%m.%Y').date()
            except: continue
            ms.append({'code':str(r['Код']),'name':str(r['Контрольная точка']),'date':d,'resp':str(r.get('Ответственный','')),'status':str(r.get('Статус','Не начато')),'crit':str(r.get('Критичность',''))})
        return ms
    except Exception as e:
        logger.error(f'KT error: {e}'); return []

def se(s): return {'Завершено':'✅','Выполнено':'✅','В работе':'🔄','Просрочено':'🔴'}.get(s,'⭕')
def ce(c): return {'Критическая':'🔴','Высокая':'🟠','Средняя':'🟡'}.get(c,'⚪')

def digest(tasks,ms):
    t=date.today(); w=t+timedelta(days=7)
    td=[x for x in tasks if x['end']==t and x['status']!='Завершено']
    ov=[x for x in tasks if x['end']<t and x['status']!='Завершено']
    wk=[x for x in tasks if t<x['end']<=w and x['status']!='Завершено']
    L=[f'🦕 *ПМО Динозавры · {t.strftime("%d.%m.%Y")}*',f'_Поставка 12 фигур SANHE → ООО «Парк Сказка»_','']
    if ov:
        L.append('🔴 *ПРОСРОЧЕНО:*')
        for x in ov[:5]: L.append(f'  `{x["code"]}` {x["name"][:40]} — {x["resp"]} *(+{(t-x["end"]).days}дн)*')
        L.append('')
    if td:
        L.append('📌 *Сегодня:*')
        for x in td[:8]: L.extend([f'  {se(x["status"])} `{x["code"]}` {x["name"][:40]}',f'     └ {x["resp"]}'])
        L.append('')
    else: L.append('📌 *Сегодня:* задач с дедлайном нет')

    if wk:
        L.append(f'📅 *На 7 дней ({len(wk)} задач):*')
        for x in sorted(wk,key=lambda x:x['end'])[:8]: L.append(f'  ⭕ `{x["code"]}` {x["name"][:35]} — {x["end"].strftime("%d.%m")}')
        L.append('')
    L.append('🔗 https://galkinva.github.io/pmo-dinosaurs/')
    return '\n'.join(L)

def milestone_alert(ms):
    t=date.today(); up=[]
    for m in ms:
        if m['status'] in ('Выполнено','Завершено'): continue
        d=(m['date']-t).days
        if 0<=d<=3: up.append((d,m))
    if not up: return None
    L=['⚠️ *Приближающиеся вехи:*','']
    for d,m in sorted(up):
        w='🔴 *СЕГОДНЯ*' if d==0 else ('🟠 *Завтра*' if d==1 else f'🟡 Через {d}дн ({m["date"].strftime("%d.%m")})')
        L.extend([f'{ce(m["crit"])} `{m["code"]}` {m["name"][:45]}',f'  └ {w} · {m["resp"]}',''])
    return '\n'.join(L)

def all_milestones(ms):
    t=date.today(); L=['📍 *Реестр контрольных точек:*','']
    for m in ms:
        d=(m['date']-t).days
        if m['status'] in ('Выполнено','Завершено'): mk,ti='✅','выполнено'
        elif d<0: mk,ti='🔴',f'просрочено на {-d}дн'
        elif d==0: mk,ti='🔴','СЕГОДНЯ'
        elif d<=3: mk,ti='🟠',f'через {d}дн'
        elif d<=7: mk,ti='🟡',f'через {d}дн'
        else: mk,ti='⭕',m['date'].strftime('%d.%m.%Y')
        L.extend([f'{mk} `{m["code"]}` {m["name"][:45]}',f'  └ {ti} · {m["resp"]}'])
    return '\n'.join(L)

async def cmd_start(u,c): await u.message.reply_text('🦕 *PMO Bot — Парковая Инфраструктура*\n\n/status — статус проекта\n/tasks — задачи на 7 дней\n/milestones — все вехи\n\n• 09:00 МСК пн–пт — дайджест\n• 09:05 ежедневно — вехи за 3дн',parse_mode='Markdown')

async def cmd_status(u,c):
    t=date.today(); dl=date(2026,7,28); tasks=get_tasks()
    done=sum(1 for x in tasks if x['status']=='Завершено'); total=len(tasks)
    await u.message.reply_text(f'📊 *Статус проекта · {t.strftime("%d.%m.%Y")}*\n\n⏱ До дедлайна: *{(dl-t).days} дн.* (28.07.2026)\n📋 Выполнено: *{done}/{total}*\n\n🔗 https://galkinva.github.io/pmo-dinosaurs/',parse_mode='Markdown')

async def cmd_tasks(u,c):
    tasks=get_tasks()
    if not tasks: await u.message.reply_text('⚠️ Не удалось загрузить задачи.'); return
    await u.message.reply_text(digest(tasks,get_milestones()),parse_mode='Markdown')

async def cmd_milestones(u,c):
    ms=get_milestones()
    if not ms: await u.message.reply_text('⚠️ Не удалось загрузить вехи.'); return
    await u.message.reply_text(all_milestones(ms),parse_mode='Markdown')

async def job_digest(bot):
    if date.today().weekday()>=5: return
    await bot.send_message(chat_id=CHAT_ID,text=digest(get_tasks(),get_milestones()),parse_mode='Markdown')

async def job_alert(bot):
    t=milestone_alert(get_milestones())
    if t: await bot.send_message(chat_id=CHAT_ID,text=t,parse_mode='Markdown')

def main():
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start',cmd_start))
    app.add_handler(CommandHandler('status',cmd_status))
    app.add_handler(CommandHandler('tasks',cmd_tasks))
    app.add_handler(CommandHandler('milestones',cmd_milestones))
    sch=AsyncIOScheduler(timezone=TZ)
    sch.add_job(lambda:asyncio.create_task(job_digest(app.bot)),'cron',hour=9,minute=0)
    sch.add_job(lambda:asyncio.create_task(job_alert(app.bot)),'cron',hour=9,minute=5)
    sch.start()
    logger.info('Bot running...')
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=='__main__':
    main()
