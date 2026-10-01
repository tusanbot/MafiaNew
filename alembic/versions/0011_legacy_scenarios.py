from alembic import op
import sqlalchemy as sa

revision = "0011_legacy_scenarios"
down_revision = "0010_challenge_mode"
branch_labels = None
depends_on = None

SCENARIOS = [
 ("test_2","سناریو تستی 2",2,"limited",1,["mafia","citizen"]),
 ("russian_6","روسی 6",6,"free",None,["mafia","mafia","citizen","citizen","citizen","citizen"]),
 ("interrogator_10","بازپرس",10,"free",None,["interrogator","citizen","citizen","sheyad","invulnerable","researcher","nato","doctor","detective","mafia_chief"]),
 ("capo","کاپو",10,"free",None,["detective","citizen","citizen","executioner","heir","suspect","den_mafia","apothecary","armorer","wizard"]),
 ("godfather_jack","پدرخوانده-جک",11,"limited",1,["constantine","citizen","citizen","citizen","godfather","leon","watson","matador","jack","goodman","hometown"]),
 ("godfather_nostra","پدرخوانده-نوسترا",11,"limited",1,["constantine","citizen","citizen","citizen","godfather","leon","watson","matador","nostradamus","goodman","hometown_kane"]),
 ("godfather_sherlock","پدرخوانده-شرلوک",11,"limited",1,["constantine","citizen","citizen","citizen","godfather","leon","watson","matador","sherlock","goodman","hometown_kane"]),
 ("el_clasico","الکلاسیکو",11,"limited",1,["moreno","pablo_escobar","bridget","juan","bonaparte","citizen","blanco","martinez","chaplin","churchill","citizen"]),
 ("gambler","قمار باز",11,"limited",1,["mason","blacksmith","gambler","gunner","cowboy","mistress","king_slayer","psychologist","spider","terrorist","glasses_maker"]),
 ("zodiac","زودیاک",12,"limited",1,["magician","gunner","citizen","ocean","protector","professional","al_capone","bomber","doctor","detective","citizen","zodiac"]),
 ("classic_12","کلاسیک 12",12,"limited",1,["mason","cowboy","mafia_chief","doctor","saboteur","sniper","bartender","spy","priest","gunner","natasha","invulnerable"]),
 ("classic_13","کلاسیک 13",13,"limited",1,["mason","cowboy","mafia_chief","novice","doctor","saboteur","sniper","bartender","spy","priest","gunner","natasha","invulnerable"]),
]
ROLES = [
 ("citizen","شهروند ساده","citizen","شهروند عادی"),("constantine","کنستانتین","citizen","احیای محدود بازیکن حذف‌شده"),
 ("leon","لئون","citizen",""),("watson","دکتر واتسون","citizen","نجات"),("hometown","همشهری","citizen","نقش اطلاعاتی"),
 ("hometown_kane","همشهری کین","citizen","استعلام مافیا"),("doctor","دکتر","citizen","نجات"),
 ("detective","کارآگاه","citizen","استعلام ساید/هویت"),("interrogator","بازپرس","citizen","نقش اطلاعاتی"),
 ("researcher","محقق","citizen",""),("invulnerable","روئین‌تن","citizen","مقاومت در برابر شلیک"),
 ("gunner","تفنگدار","citizen","اعطای اسلحه"),("sniper","اسنایپر","citizen","شلیک محدود"),
 ("professional","حرفه‌ای","citizen","شلیک و تشخیص هویت"),("ocean","اوشن","citizen","بیدارکردن/فعال‌کردن"),
 ("protector","محافظ","citizen","حفاظت"),("mason","ماسون","citizen","شناخت/شبکه شهروندی"),
 ("cowboy","کابوی","citizen","نقش اکشن‌محور"),("bartender","ساقی","citizen","اختلال/معکوس‌کردن قابلیت شبانه"),
 ("priest","کشیش","citizen","مقابله با سایلنت ناتاشا"),("blacksmith","آهنگر","citizen",""),
 ("psychologist","روان‌شناس","citizen",""),("spider","عنکبوت","citizen",""),("glasses_maker","عینک‌ساز","citizen",""),
 ("heir","وارث","citizen","به ارث بردن قابلیت"),("suspect","مظنون","citizen","استعلام مثبت/مافیایی در قوانین سناریو"),
 ("armorer","زره‌ساز","citizen","زره و محافظت"),("apothecary","عطار","citizen","زهر و پادزهر"),
 ("bridget","دکتر بریجیت","citizen","نجات"),("bonaparte","بناپارت","citizen","هدف‌گیری برای بیداری بعدی"),
 ("martinez","مارتینز","citizen","شلیک و تشخیص هویت"),("moreno","مورنو","citizen","تفنگ جنگی و مشقی"),
 ("chaplin","چاپلین","citizen","محافظت در برابر بعضی تغییرات نقش"),
 ("mafia","مافیا","mafia",""),("godfather","پدرخوانده","mafia","رهبر و فرمانده شلیک"),
 ("matador","ماتادور","mafia","بستن قابلیت"),("goodman","گودمن","mafia","خرید/تغییر شهروند"),
 ("pablo_escobar","پابلو اسکوبار","mafia","پدرخوانده و صاحب شلیک"),("juan","خوان","mafia","ماتادور؛ بستن قابلیت"),
 ("blanco","بلانکو","mafia","گودمن؛ خرید/تغییر"),("al_capone","آل کاپون","mafia",""),
 ("bomber","بمب‌گذار","mafia","قرار دادن بمب"),("magician","شعبده‌باز","mafia","اختلال قابلیت شبانه"),
 ("executioner","جلاد","mafia","حدس نقش و حذف ویژه"),("wizard","جادوگر","mafia","اختلال/معکوس قابلیت"),
 ("den_mafia","دن مافیا","mafia","رهبر و فرمانده شلیک؛ استعلام منفی"),
 ("sheyad","شیاد","mafia",""),("nato","ناتو","mafia",""),("mafia_chief","رئیس مافیا","mafia","رهبر و مدیریت شلیک"),
 ("gambler","قمارباز","mafia",""),("mistress","معشوقه","mafia",""),("king_slayer","شاهکش","mafia",""),
 ("terrorist","تروریست","mafia",""),("spy","جاسوس","mafia","اطلاعاتی/نفوذی"),
 ("saboteur","خرابکار","mafia","خنثی/برگرداندن شلیک"),("natasha","ناتاشا","mafia","ساکت کردن برای روز بعد"),
 ("jack","جک گنجیشکه","independent",""),("nostradamus","نوستراداموس","independent",""),
 ("sherlock","شرلوک","independent",""),("churchill","چرچیل","independent","شرط برد مبتنی بر پیش‌بینی خروج"),
 ("zodiac","زودیاک","independent",""),("novice","نوفیس","independent","")
]

def upgrade():
    op.add_column("scenarios", sa.Column("challenge_limit", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE scenarios SET challenge_limit=1 WHERE challenge_mode='limited'"))
    for key,name,players,mode,limit,roles in SCENARIOS:
        op.execute(sa.text("""
            INSERT INTO scenarios(key,name_fa,min_players,max_players,enabled,challenge_mode,challenge_limit)
            VALUES (:key,:name,:minp,:maxp,true,:mode,:limit)
            ON CONFLICT (key) DO UPDATE SET name_fa=EXCLUDED.name_fa,min_players=EXCLUDED.min_players,max_players=EXCLUDED.max_players,enabled=true,challenge_mode=EXCLUDED.challenge_mode,challenge_limit=EXCLUDED.challenge_limit
        """), {"key":key,"name":name,"minp":players,"maxp":players,"mode":mode,"limit":limit})
    for key,name,team,desc in ROLES:
        op.execute(sa.text("""
            INSERT INTO roles(key,name_fa,team,description)
            VALUES (:key,:name,:team,:desc)
            ON CONFLICT (key) DO UPDATE SET name_fa=EXCLUDED.name_fa,team=EXCLUDED.team,description=EXCLUDED.description
        """), {"key":key,"name":name,"team":team,"desc":desc})

def downgrade():
    for key, *_ in SCENARIOS:
        op.execute(sa.text("DELETE FROM scenarios WHERE key=:key"), {"key":key})
    keys=[r[0] for r in ROLES]
    op.execute(sa.text("DELETE FROM roles WHERE key = ANY(:keys)"), {"keys":keys})
    op.drop_column("scenarios","challenge_limit")
