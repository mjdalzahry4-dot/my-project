# نظام إدارة مشاريع التخرج GPMS

تطبيق عربي لإدارة طلبات مجموعات مشاريع التخرج. يضم واجهة ويب ثابتة (المرحلة 1) وتحليل المتطلبات (المرحلة 2) وتصميم قاعدة البيانات وواجهات API (المرحلة 3) وخادم Django REST Framework (المرحلة 4)، وربط الواجهة بالخادم (المرحلة 5)، واختبارات شاملة وإصلاحات (المرحلة 6)، وتهيئة نشر موثقة (المرحلة 7). لم يُنشر النظام.

## تشغيل الواجهة التجريبية

```powershell
python -m http.server 8000 --directory frontend
```

ثم افتح <http://localhost:8000>. لتسجيل الدخول يجب تشغيل API أدناه.

## تشغيل خادم API محليًا

يتطلب Python وحزم `backend/requirements.txt`. أنشئ بيئة افتراضية وثبّت الحزم:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DJANGO_SECRET_KEY = 'ضع-مفتاحا-محليا-عشوائيا-هنا'
$env:DJANGO_DEBUG = 'true'
.venv\Scripts\python.exe backend\manage.py migrate
.venv\Scripts\python.exe backend\manage.py createsuperuser
.venv\Scripts\python.exe backend\manage.py runserver 8001
```

أول حساب فائق يُنشأ بدور العميد، ويمكنه الدخول إلى لوحة الإدارة على <http://127.0.0.1:8001/admin/> وإعداد الأقسام والحسابات. تتوفر نقاط API على <http://127.0.0.1:8001/api/v1/>. انسخ `.env.example` كمرجع للمتغيرات؛ الإعدادات تقرأ من بيئة العملية ولا تحمل ملف `.env` تلقائيًا. عند عدم ضبط `DATABASE_URL` يستخدم الخادم SQLite للتطوير. PostgreSQL مدعوم عبر `DATABASE_URL`.

## النشر على Render

المشروع Django/Python وليس Node.js، لذا لا يحتاج `package.json` أو `npm start`. ملف `render.yaml` يعرّف خدمة Django التي تعرض الواجهة من `frontend/` وواجهة API على النطاق نفسه، ويستخدم `build.sh` لتثبيت المتطلبات وتجميع الملفات الثابتة. يتطلب النشر اختيار قاعدة PostgreSQL على Render وإضافة `DATABASE_URL` من إعدادات الخدمة. اختر قاعدة دائمة إذا كان سيُخزن فيها عمل حقيقي؛ قاعدة Render المجانية تنتهي بعد 30 يومًا.

عند إنشاء Blueprint، أدخل في `CORS_ORIGINS` الأصل الكامل فقط إذا كانت الواجهة على نطاق منفصل؛ لـGitHub Pages استخدم `https://YOUR_GITHUB_USERNAME.github.io` بلا مسار. عند استضافة الواجهة عبر خدمة Django نفسها اتركه فارغًا. وإذا استُخدم GitHub Pages، غيّر `frontend/runtime-config.js` إلى عنوان API المنشور بصيغة `https://YOUR_API_HOST.onrender.com/api/v1`.

تتضمن إعدادات Render إنشاء `DJANGO_SECRET_KEY` تلقائيًا، وتشغيل migrations، وربط المنفذ الذي توفره Render عبر `PORT`. لا ترفع `.env` أو ملف قاعدة بيانات التطوير.

بعد أول نشر، أنشئ حساب العميد في قاعدة الإنتاج من Render Shell بالأمر `python backend/manage.py createsuperuser`؛ حسابات قاعدة SQLite المحلية مستبعدة من الحزمة عمدًا.

## نطاق المرحلتين 4 و5 المنفذ

- نماذج وترحيل قاعدة البيانات للعلاقات والأدوار والطلبات ومراجعاتها والقرارات والمجموعات والمشاريع والعضويات والإسنادات والتسليمات والملاحظات والتدقيق والرموز وصندوق الأحداث.
- واجهات المصادقة والجلسات وCSRF، الأقسام، طلبات المجموعات، قرارات العميد، المجموعات والمشاريع وملاحظاتها وسجل التدقيق.
- صلاحيات حسب الدور والنطاق، تحقق من المدخلات، منع اسم المستخدم المكرر بعد التطبيع، منع عضوية الطالب في مجموعتين نشطتين، واعتماد ذري يتراجع بالكامل عند الفشل.
- الحسابات التي تنشأ بعد اعتماد الطلب تظل غير مفعلة حتى تعيين كلمة مرورها.
- الواجهة تستخدم جلسات الخادم لتسجيل الدخول واستعادة الجلسة وتسجيل الخروج، وتحمل الطلبات والأقسام والمشرفين والمجموعات والمشاريع وسجل التدقيق من API.
- إنشاء طلب المجموعة وإرساله إلى العميد، واتخاذ قرار العميد، وقراءة/حفظ ملاحظات المشروع تتم على الخادم.
- يسمح الخادم باتصال الواجهة المحلي من `http://localhost:8000` و`http://127.0.0.1:8000` لحسابات الجلسة وCSRF؛ في الإنتاج اضبط `CORS_ORIGINS` عند استخدام نطاق واجهة منفصل.

## نقاط API الأساسية

- `GET /api/v1/health/`
- `GET /api/v1/auth/csrf/`, `POST /api/v1/auth/login/`, `POST /api/v1/auth/logout/`, `GET /api/v1/auth/me/`
- `POST /api/v1/auth/password-reset-requests/`, `POST /api/v1/auth/one-time-password/{activate|reset}/`
- `GET /api/v1/departments/`
- `GET /api/v1/supervisors/`
- `GET|POST /api/v1/group-requests/`, `GET /api/v1/group-requests/{id}/`, `POST /api/v1/group-requests/{id}/submit/`
- قرارات العميد: `POST /api/v1/group-requests/{id}/{approve|return|reject}/`
- `GET /api/v1/groups/`, `GET /api/v1/groups/{id}/`, `GET /api/v1/projects/`, `GET /api/v1/projects/{id}/`, وملاحظات المشروع عبر `/api/v1/projects/{id}/notes/`
- `GET /api/v1/audit-log/`

## التحقق الذي أُجري

بعد إعداد بيئة Python محلية، نُفذت أوامر فحص Django، والتحقق من عدم وجود ترحيلات ناقصة، وتطبيق الترحيلات على SQLite. لتشغيل اختبارات الخادم:

```powershell
$env:DJANGO_SECRET_KEY = 'مفتاح-اختبار-محلي'
$env:DJANGO_DEBUG = 'true'
.venv\Scripts\python.exe backend\manage.py test gpms
```

لاختبار تنبيه الواجهة عند انقطاع الاتصال أثناء استعادة الجلسة:

```powershell
node --test integration.test.cjs
```

راجع [تقرير المرحلة 4](STAGE4_REPORT.md) و[تقرير المرحلة 5](STAGE5_REPORT.md) و[تقرير المرحلة 6](STAGE6_REPORT.md)، ودليل [التهيئة للنشر](DEPLOYMENT.md). لم يُتصل بقاعدة PostgreSQL فعلية، ولم تُختبر استعادة نسخة أو تُنفذ عملية نشر.

## قيود معروفة قبل المراحل التالية

- تسليمات الملفات والتقويم وإدارة المستخدمين لا تتوفر كواجهات متصلة في المرحلة الحالية.
- لا يوجد عامل يرسل رسائل البريد أو يعالج صندوق الأحداث؛ لذلك لا يعمل إيصال رابط التفعيل أو استعادة كلمة المرور حتى ربط قناة توصيل آمنة. الواجهة الخلفية لا تضع الرموز السرية في الأحداث.
- لا توجد واجهات رفع/تنزيل ملفات بعد؛ يلزم اعتماد سياسة الجامعة للأنواع والأحجام والاحتفاظ والتخزين.
- لا تزال بعض قرارات الجامعة مفتوحة في `ANALYSIS.md`، ومنها نطاق تفرد رمز المجموعة والحدود النهائية لحجم المجموعة. لم يُفرض نطاق تفرد للرمز بالتخمين.
- لم يُجر اختبار اتصال PostgreSQL أو إعداد إنتاج أو نشر أو اختبار أمني خارجي.
