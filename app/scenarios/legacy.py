from app.scenarios.registry import RoleDefinition, ScenarioDefinition

def R(k,n,t,d=""): return RoleDefinition(k,n,t,d)
ROLES={}
def add(k,n,t,d=""): ROLES[k]=R(k,n,t,d)

# Shared roles
for k,n,d in [
("citizen","شهروند ساده","شهروند عادی"),("constantine","کنستانتین","احیای محدود بازیکن حذف‌شده"),("leon","لئون","دو شلیک و یک جلیقه؛ جزئیات دقیق نسخه سناریو ملاک است"),
("watson","دکتر واتسون","نجات"),("hometown","همشهری","نقش اطلاعاتی"),("hometown_kane","همشهری کین","استعلام مافیا"),
("doctor","دکتر","نجات"),("detective","کارآگاه","استعلام ساید/هویت"),("interrogator","بازپرس","نقش اطلاعاتی"),
("researcher","محقق",""),("invulnerable","روئین‌تن","مقاومت در برابر شلیک"),("gunner","تفنگدار","اعطای اسلحه"),
("sniper","اسنایپر","شلیک محدود"),("professional","حرفه‌ای","شلیک و تشخیص هویت"),("ocean","اوشن","بیدارکردن/فعال‌کردن"),
("protector","محافظ","حفاظت"),("mason","ماسون","شناخت/شبکه شهروندی"),("cowboy","کابوی","نقش اکشن‌محور"),
("bartender","ساقی","اختلال/معکوس‌کردن قابلیت شبانه"),("priest","کشیش","مقابله با سایلنت ناتاشا"),
("blacksmith","آهنگر","هر شب می‌تواند یک زره بدهد؛ با فعال شدن زره، بازیکن از شلیک یا اجماع جان سالم به‌در می‌برد."),("psychologist","روان‌شناس","هر شب قابلیت شلیک دارد، اما تأیید شلیک را به بازیکن دیگری واگذار می‌کند؛ در صورت تأیید، شلیک فایربک ندارد."),("spider","عنکبوت","می‌تواند دو نفر را به هم ببافد تا در صورت خروج هرکدام، نفر دوم نیز همراه او خارج شود."),("glasses_maker","عینک‌ساز","هر شب می‌تواند یک عینک بدهد؛ عینک به شهروند امکان استعلام و عینک به مافیا امکان ردیابی می‌دهد."),
("heir","وارث","به ارث بردن قابلیت"),("suspect","مظنون","استعلام مثبت/مافیایی در قوانین سناریو"),
("armorer","زره‌ساز","زره و محافظت"),("apothecary","عطار","زهر و پادزهر"),("bridget","دکتر بریجیت","نجات"),
("bonaparte","بناپارت","هدف‌گیری برای بیداری بعدی"),("martinez","مارتینز","شلیک و تشخیص هویت"),
("moreno","مورنو","تفنگ جنگی و مشقی"),("chaplin","چاپلین","محافظت در برابر بعضی تغییرات نقش")
]: add(k,n,"citizen",d)

# Mafia
for k,n,d in [
("mafia","مافیا","قابلیت ویژه ندارد؛ شب با تیم مافیا برای انتخاب هدف مشورت می‌کند."),("godfather","پدرخوانده","رهبر و فرمانده شلیک"),("matador","ماتادور","بستن قابلیت"),
("goodman","گودمن","خرید/تغییر شهروند"),("pablo_escobar","پابلو اسکوبار","پدرخوانده و صاحب شلیک"),
("juan","خوان","ماتادور؛ بستن قابلیت"),("blanco","بلانکو","گودمن؛ خرید/تغییر"),
("al_capone","آل کاپون","رئیس مافیا و صاحب شلیک در سناریوی زودیاک؛ جزئیات نسخه سناریو ملاک است."),("bomber","بمب‌گذار","قرار دادن بمب"),("magician","شعبده‌باز","اختلال قابلیت شبانه"),
("executioner","جلاد","حدس نقش و حذف ویژه"),("wizard","جادوگر","اختلال/معکوس قابلیت"),
("den_mafia","دن مافیا","رهبر و فرمانده شلیک؛ استعلام منفی"),
("sheyad","شیاد",""),("nato","ناتو",""),("mafia_chief","رئیس مافیا","رهبر و مدیریت شلیک"),
("gambler","قمارباز","هر شب اختیار قمار سنگ، کاغذ، قیچی دارد؛ در صورت انجام قمار، فرد بازنده شب اعلام و کشته می‌شود."),("mistress","معشوقه","پس از مرگ معشوقه، تیم مافیا در شب بعد یک شات خواهد داشت."),("king_slayer","شاهکش","می‌تواند فردی را با حدس نقش، تحت هر شرایطی از بازی خارج کند."),("terrorist","تروریست","در صورت خروج یا کشته شدن، می‌تواند یک نفر را به انتخاب خودش همراه خود از بازی خارج کند."),
("spy","جاسوس","اطلاعاتی/نفوذی"),("saboteur","خرابکار","خنثی/برگرداندن شلیک"),("natasha","ناتاشا","ساکت کردن برای روز بعد")
]: add(k,n,"mafia",d)

for k,n,d in [
("jack","جک گنجیشکه",""),("nostradamus","نوستراداموس",""),("sherlock","شرلوک",""),
("churchill","چرچیل","شرط برد مبتنی بر پیش‌بینی خروج"),("zodiac","زودیاک",""),("novice","نوفیس","در نسخه ۱۳ نفره مستقل است؛ قابلیت ویژه در اطلاعات ارائه‌شده مشخص نشده است.")
]: add(k,n,"independent",d)

def S(k,n,roles,mode="limited",limit=1):
    return ScenarioDefinition(k,n,len(roles),len(roles),tuple(ROLES[x] for x in dict.fromkeys(roles)),
                              mode,limit,tuple(roles))

SCENARIOS=(
S("test_2","سناریو تستی 2",("mafia","citizen")),
S("russian_6","روسی 6",("mafia","mafia","citizen","citizen","citizen","citizen"),"free",None),
S("interrogator_10","بازپرس",("interrogator","citizen","citizen","sheyad","invulnerable","researcher","nato","doctor","detective","mafia_chief"),"free",None),
S("capo","کاپو",("detective","citizen","citizen","executioner","heir","suspect","den_mafia","apothecary","armorer","wizard"),"free",None),
S("godfather_jack","پدرخوانده-جک",("constantine","citizen","citizen","citizen","godfather","leon","watson","matador","jack","goodman","hometown")),
S("godfather_nostra","پدرخوانده-نوسترا",("constantine","citizen","citizen","citizen","godfather","leon","watson","matador","nostradamus","goodman","hometown_kane")),
S("godfather_sherlock","پدرخوانده-شرلوک",("constantine","citizen","citizen","citizen","godfather","leon","watson","matador","sherlock","goodman","hometown_kane")),
S("el_clasico","الکلاسیکو",("moreno","pablo_escobar","bridget","juan","bonaparte","citizen","blanco","martinez","chaplin","churchill","citizen")),
S("gambler","قمار باز",("mason","blacksmith","gambler","gunner","cowboy","mistress","king_slayer","psychologist","spider","terrorist","glasses_maker")),
S("zodiac","زودیاک",("magician","gunner","citizen","ocean","protector","professional","al_capone","bomber","doctor","detective","citizen","zodiac")),
S("classic_12","کلاسیک 12",("mason","cowboy","mafia_chief","doctor","saboteur","sniper","bartender","spy","priest","gunner","natasha","invulnerable")),
S("classic_13","کلاسیک 13",("mason","cowboy","mafia_chief","novice","doctor","saboteur","sniper","bartender","spy","priest","gunner","natasha","invulnerable")),
)
ROLE_DEFINITIONS=tuple(ROLES.values())


def get_scenario(scenario_id: str) -> ScenarioDefinition | None:
    return next((scenario for scenario in SCENARIOS if scenario.id == scenario_id), None)
