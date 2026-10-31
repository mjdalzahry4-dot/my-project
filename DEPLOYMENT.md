# التهيئة للنشر — GitHub وNetlify وPythonAnywhere

هذه الملفات تجهز الإعدادات وخطوات النشر، ولا تعني أن النظام نُشر أو أن بيئة إنتاج حقيقية جرى اختبارها. لا تستخدم `runserver` في الإنتاج.

## الإعداد المعتمد لهذا المشروع

قاعدة الإنتاج الحالية SQLite. أبقِ ملف قاعدة البيانات نفسه وفي مساره الحالي؛ لا تضبط `DATABASE_URL` إلى PostgreSQL، ولا تنقل البيانات أو تبدّل محرك القاعدة. إعداد `config.settings_production` يحافظ على `backend/db.sqlite3` افتراضيًا، ويقبل `sqlite:////مسار/مطلق/إلى/db.sqlite3` إذا كان ملف الإنتاج في مسار آخر. لا تشغّل migrations إلا عند وجود ترحيل جديد وبعد أخذ نسخة احتياطية والتحقق من إمكانية استعادتها.

GitHub مستودع للكود، وNetlify ينشر `frontend/` كواجهة ثابتة، وPythonAnywhere يشغّل Django مع ملف SQLite الحالي. GitHub Pages لا يشغّل Python/Django؛ لذلك لا يصلح وحده لاستضافة الخادم.

## متطلبات التشغيل

- نطاق DNS وشهادة HTTPS صالحة للواجهة وAPI، وخادم ويب/وكيل عكسي يُنهي TLS ويُمرر API إلى خادم WSGI/ASGI داخلي غير مكشوف للعامة.
- مخزن أسرار لحفظ `DJANGO_SECRET_KEY` خارج Git وسجلات التشغيل.
- مساحة نسخ احتياطي مشفرة ومقيدة الوصول لملف SQLite، مع اختبار دوري للاستعادة.
- لم تُنفذ وظائف البريد أو الرسائل؛ التفعيل يدوي من واجهة العميد، واستعادة كلمة المرور تتطلب مراجعة رئيس القسم.

تظل SQLite قاعدة المشروع. يقيّد هذا الاختيار التوسع والكتابات المتزامنة؛ أُبقي كما طلبت، مع نسخ احتياطي واختبار استعادة قبل أي نشر يمس البيانات.

1. ادفع المستودع إلى GitHub بعد ضبط remote لحسابك. لا ترفع `.env` أو `backend/db.sqlite3` أو أي نسخة احتياطية.
2. اربط مستودع GitHub بخدمة Netlify، وحدد `frontend/` مجلدًا للنشر. يضبط `netlify.toml` هذا المسار تلقائيًا.
3. على PythonAnywhere، أنشئ تطبيق ويب Django من تبويب Web، واربطه بمستودع GitHub وثبت المتطلبات من `backend/requirements.txt` داخل virtualenv.
4. احتفظ بملف SQLite الحالي في مكانه، وتحقق من قيمة `NAME` الفعلية في إعداد WSGI الجاري قبل اختيار `config.settings_production`. لا تنشئ قاعدة جديدة ولا تهيئ ملفًا فارغًا بديلًا.
5. اضبط متغيرات البيئة في ملف WSGI الخاص بالتطبيق قبل استدعاء `get_wsgi_application`. ملف `.env.example` قالب توضيحي فقط؛ Django لا يحمّله تلقائيًا. ضع القيم الحقيقية في ملف WSGI على PythonAnywhere أو حمّل ملف أسرار خاصًا خارج Git. لا تضع أسرارًا حقيقية في المستودع.
6. في ملف WSGI الذي يوفره تبويب Web، أضف المسار الفعلي إلى مجلد `backend` (المجلد الذي يحتوي `manage.py`) إلى `sys.path`، واضبط المتغيرات ثم استورد Django. مثال هيكلي، استبدل المسارات والقيم بقيم حسابك:

   ```python
   import os
   import sys

   sys.path.insert(0, "/home/USERNAME/PROJECT/backend")
   os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_production"
   os.environ["DJANGO_SECRET_KEY"] = "ضع_هنا_مفتاحًا_عشوائيًا_حقيقيًا_طويلًا"
   os.environ["DJANGO_ALLOWED_HOSTS"] = "mjdkhaled1.pythonanywhere.com"
   os.environ["CORS_ORIGINS"] = "https://mjdkhaled1.pythonanywhere.com,https://incandescent-stardust-31fbdc.netlify.app"
   # اترك DATABASE_URL غير مضبوط لاستخدام backend/db.sqlite3 الحالي.
   # إذا كان الملف في مكان آخر، استخدم DATABASE_URL بصيغة sqlite:////مسار/مطلق/للملف.

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```

   احتفظ بالمفتاح سريًا. لا تضبط `DATABASE_URL` إلى محرك آخر، ولا تنفذ أوامر تهيئة قاعدة بيانات. عند تشغيل أي migration مستقبلًا، خذ نسخة احتياطية قابلة للاستعادة أولًا.
7. اربط `/static/` بمجلد `backend/staticfiles` من إعدادات Web، ثم أعد تحميل التطبيق. لا حاجة إلى migration للتغييرات الحالية.

`frontend/runtime-config.js` يرسل طلبات الواجهة المنشورة إلى API PythonAnywhere. تسجيل الدخول يعيد رمز DRF مؤقتًا (12 ساعة) ترسله الواجهة لاحقًا بترويسة `Authorization: Token ...`؛ لا تعتمد الواجهة على ملفات تعريف ارتباط الطرف الثالث. إعدادات الإنتاج تسمح بأصول HTTPS المصرح بها في `CORS_ORIGINS` فقط، وتسمح بترويسة Authorization في طلبات CORS. `CSRF_TRUSTED_ORIGINS` يبقى مضبوطًا لصفحات Django الإدارية. عناوين HTTP على localhost تبقى لإعداد التطوير المحلي.

## إعداد Render البديل

يوفر `render.yaml` إعداد Blueprint لخدمة Django واحدة تقدم الواجهة من `frontend/` وAPI ولوحة الإدارة من النطاق نفسه. ارفع المستودع، ثم أنشئ Blueprint في Render واختر المستودع. لا يحتوي الإعداد على قاعدة بيانات لتجنب إنشاء مورد مدفوع دون اختيارك؛ أنشئ PostgreSQL في Render، ثم أضف رابط الاتصال الداخلي إلى `DATABASE_URL`. اختر خطة مدفوعة لحفظ بيانات النظام على المدى الطويل؛ قواعد Render المجانية تنتهي بعد 30 يومًا. القيمة `DJANGO_SECRET_KEY` تُولّدها Render تلقائيًا.

عند مطالبة Blueprint بقيمة `CORS_ORIGINS`، اتركها فارغة عند استخدام نطاق خدمة Django نفسه للواجهة وAPI. إذا استخدمت GitHub Pages أو نطاق واجهة منفصلًا، أدخل الأصل الدقيق مثل `https://YOUR_GITHUB_USERNAME.github.io` دون مسار. عند GitHub Pages، حدّث `frontend/runtime-config.js` بعنوان API العام. واجهة API تستخدم رمز وصول، بينما تبقى جلسات Django للوحة الإدارة فقط.

## إعداد عام

1. انسخ `deploy/env.production.example` إلى مخزن أسرار بيئة التشغيل، لا إلى Git. أنشئ `DJANGO_SECRET_KEY` جديدًا بأمر `python -c "import secrets; print(secrets.token_urlsafe(64))"`، وأدخل قيم النطاقات وقاعدة البيانات الفعلية في مخزن الأسرار.
2. استخدم `DATABASE_SSLMODE=verify-full` وشهادة CA الصحيحة في `DATABASE_SSLROOTCERT`. لا تخفض التحقق من هوية الخادم لمجرد تجاوز مشكلة إعداد.
3. املأ `DJANGO_ALLOWED_HOSTS` بأسماء API فقط، و`CORS_ORIGINS` بأصول الواجهة (`https://...` بلا مسار). ضع الواجهة وAPI تحت النطاق الأساسي نفسه قدر الإمكان. إن كانت الواجهة وAPI من الأصل نفسه، اترك CORS فارغًا.
4. عند الاستضافة خارج خدمة Django، في `frontend/runtime-config.js` ضع عنوان API العام بصيغة `https://api.example.edu/api/v1`. هذا العنوان ليس سرًا. لا تضع أي اعتماد قاعدة بيانات أو مفتاح خاص في ملف JavaScript.
5. لا تضبط `DJANGO_TRUST_PROXY_SSL_HEADER=true` إلا إذا كان الوكيل الموثوق أمام Django يزيل قيمة `X-Forwarded-Proto` التي يرسلها العميل ويضع بنفسه القيمة الصحيحة. امنع الوصول المباشر العام إلى خادم Django.
6. أبقِ `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` و`DJANGO_SECURE_HSTS_PRELOAD` معطلين حتى تثبت ملكية كل نطاق فرعي واستقرار HTTPS عليها؛ HSTS طويل العمر قد يمنع العودة إلى HTTP للزوار.
7. أنشئ ملف كلمة مرور PostgreSQL بصيغة pgpass خارج مجلد الموقع، واضبط `PGPASSFILE`. على Windows يجب أن تسمح ACL لحساب الخدمة المقصود فقط. صيغة السطر `host:port:database:username:password`؛ اهرب `:` و`\` في القيم وفق صيغة pgpass. لا تمرر كلمة المرور كخيار سطر أوامر.

## تسلسل إصدار يدوي

نفذ هذه الخطوات من صورة إصدار محفوظة ومعرّفة برقم إصدار:

1. امنع الكتابة/حوّل الحركة إلى وضع صيانة إذا تطلبت قاعدة البيانات ذلك، وخذ نسخة احتياطية واستخرج معلوماتها قبل الترحيل.
2. ثبّت الحزم المحددة في `backend/requirements.txt` داخل بيئة الإصدار، ثم نفذ:

   ```powershell
   $env:DJANGO_SETTINGS_MODULE = 'config.settings_production'
   python backend/manage.py check --deploy
   python backend/manage.py migrate --check
   python backend/manage.py migrate --noinput
   python backend/manage.py migrate --check
   python backend/manage.py collectstatic --noinput
   ```

3. شغّل خادم WSGI/ASGI إنتاجيًا خلف الوكيل، لا خادم التطوير. وجّه الواجهة الثابتة إلى HTTPS، ومرّر واجهة API إلى الأصل المسجل في CORS وإعداد `frontend/runtime-config.js`.
4. افحص `GET /api/v1/health/`، وسجلات بدء الخدمة، وتسجيل الدخول ومسار طلب تجريبي معتمد بسياسة المؤسسة قبل فتح الحركة. إعداد الصحة الحالي لا يفحص اتصال قاعدة البيانات؛ تحقق من ذلك أيضًا بأمر إداري مناسب أو استعلام تشغيل معتمد.
5. احتفظ بسجل الإصدار السابق ومخرجات النسخة الاحتياطية. راقب سجل stdout/stderr عبر منصة الاستضافة مع إخفاء الأسرار وتدوير/احتفاظ تحدده سياسة المؤسسة.

ترحيلات Django قابلة لإعادة التنفيذ دون تطبيق الترحيل نفسه مرتين؛ لكن هذا لا يجعل كل تغيير بيانات قابلًا للعكس. راجع كل ترحيل يدويًا، وخذ نسخة قبل الترحيلات، وجرّبها على نسخة مرحلية من قاعدة بيانات مماثلة.

## النسخ الاحتياطي والاستعادة

تتطلب السكربتات `pg_dump`/`pg_restore` من نسخة متوافقة من أدوات PostgreSQL، و`DATABASE_URL` و`PGPASSFILE` في بيئة العملية. تحفظ النسخة بصيغة PostgreSQL المخصصة في مجلد موجود مسبقًا خارج جذر الويب:

```powershell
$env:DATABASE_URL = 'postgresql://USER:REDACTED@DB_HOST:5432/DB_NAME'
$env:PGPASSFILE = 'C:\secure\gpms.pgpass'
$env:DATABASE_SSLMODE = 'verify-full'
$env:DATABASE_SSLROOTCERT = 'C:\secure\provider-ca.pem'
.\deploy\backup-postgres.ps1 -OutputDirectory 'D:\protected-backups\gpms'
```

اختبر سلامة الأرشيف أولًا بواسطة `pg_restore --list <backup-file>`. الاستعادة **مُدمرة للكائنات الحالية في قاعدة الهدف**. لا تشغّلها على الإنتاج إلا بعد نافذة صيانة وموافقة مسؤول البيانات والتحقق من اسم القاعدة والنسخة. السكربت يتطلب اسم القاعدة حرفيًا وخيار `-ConfirmRestore`:

```powershell
.\deploy\restore-postgres.ps1 -BackupFile 'D:\protected-backups\gpms\gpms-DB_NAME-YYYYMMDDTHHMMSSZ.dump' -ConfirmDatabaseName 'DB_NAME' -ConfirmRestore
```

نفّذ أول استعادة في بيئة معزولة، ثم تحقق من ترحيلات Django وعدد السجلات وصلاحيات الأدوار ومسار العمل قبل اعتبار النسخة قابلة للاستعادة. هذه المرحلة أضافت السكربتات فقط؛ لم تتصل بقاعدة حقيقية ولم تنشئ/تستعد نسخة فعلية، لذا لم يُثبت RPO أو RTO.

## التراجع

1. أوقف استقبال الكتابات واحتفظ بالسجلات ومعرّف الإصدار.
2. إذا كان التراجع إلى نسخة تطبيق متوافقة مع المخطط الحالي كافيًا، أعد إصدار التطبيق السابق أولًا وتحقق من المسارات الأساسية.
3. إذا تطلبت التغييرات استعادة قاعدة البيانات، اتبع نافذة الاستعادة المدمرة أعلاه على القاعدة المقصودة بعد نسخة احتياطية من الحالة الحالية. لا تشغل `migrate <previous_migration>` عشوائيًا؛ افحص قابلية عكس كل ترحيل وآثار فقد البيانات.
4. تحقق من الصحة والمصادقة وعزل الوصول وسجلات الأخطاء قبل إعادة الحركة.

## بوابة ما قبل النشر

- [ ] اختيار النطاق والاستضافة ومزود PostgreSQL وتقدير التكلفة والموافقة عليها.
- [ ] حفظ الأسرار والشهادات وحساب الخدمة بصلاحيات دنيا خارج Git.
- [ ] إعداد TLS والوكيل الموثوق وDNS وCORS وCSRF و`runtime-config.js` والتحقق منها من المتصفح.
- [ ] تثبيت إصدار الخادم وإعداد إدارة خدمة وإعادة تشغيل ومراقبة وتنبيهات وسجلات واحتفاظ.
- [ ] أتمتة النسخ الاحتياطية المشفرة والاحتفاظ والتنبيه عن الفشل، ثم استعادة نسخة إلى بيئة منفصلة وقياس RPO/RTO.
- [ ] حسم سياسة الملفات والبريد قبل توفير هذه الوظائف، ثم إجراء مراجعة أمنية وخطة استجابة للحوادث.
- [ ] اعتماد خطة الصيانة والترحيل والتراجع، ثم الحصول على إذن نشر مستقل.

لا توجد عملية نشر أو شراء أو اتصال إنتاجي منفذ حاليًا.
