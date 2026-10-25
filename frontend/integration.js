const API_BASE = 'https://MjdKhaled1.pythonanywhere.com/api/v1';

// 1. دالة تسجيل الدخول الحقيقية
login = function() {
    document.querySelector('#app').innerHTML = `
        <div class="login-page">
            <section class="login-art">
                <div class="brand-lockup"><div class="brand-mark">ج</div><div><div class="brand-name">إدارة مشاريع التخرج</div></div></div>
                <div class="art-copy"><h1>مرحباً بك في<br>نظام إدارة المشاريع</h1></div>
            </section>
            <section class="login-panel">
                <form class="login-box" id="real-login-form">
                    <h2>تسجيل الدخول</h2>
                    <p>أدخل بيانات حسابك الحقيقي.</p>
                    <div class="field"><label>اسم المستخدم</label><input id="login-user" required /></div>
                    <div class="field"><label>كلمة المرور</label><input id="login-password" type="password" required /></div>
                    <div id="login-error" style="color:red; display:none; margin-bottom:10px; font-weight:bold;"></div>
                    <button type="submit" class="btn btn-primary btn-block" id="login-btn">تسجيل الدخول ←</button>
                </form>
            </section>
        </div>
    `;

    document.getElementById('real-login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const user = document.getElementById('login-user').value;
        const pass = document.getElementById('login-password').value;
        const btn = document.getElementById('login-btn');
        const err = document.getElementById('login-error');

        btn.disabled = true;
        btn.textContent = 'جاري التحقق...';
        err.style.display = 'none';

        try {
            // إرسال الطلب للخادم
            const res = await fetch('https://MjdKhaled1.pythonanywhere.com/api-token-auth/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: user, password: pass })
            });

            if (!res.ok) throw new Error('اسم المستخدم أو كلمة المرور غير صحيحة');

            const data = await res.json();
            localStorage.setItem('authToken', data.token);
            
            // جلب بيانات المستخدم
            const meRes = await fetch('https://MjdKhaled1.pythonanywhere.com/api/v1/auth/me/', {
                headers: { 'Authorization': 'Token ' + data.token }
            });
            
            if (!meRes.ok) throw new Error('حدث خطأ في جلب بيانات المستخدم');
            const meData = await meRes.json();

            // تحويل الدور
            const role = meData.role === 'department_chair' ? 'chair' : meData.role;
            
            // تحديث الحالة
            state.apiUser = meData;
            state.role = role;
            
            if (roles[role]) {
                roles[role].name = meData.display_name || meData.username;
                roles[role].initials = (meData.display_name || meData.username).substring(0, 2);
            }
            
            state.page = 'overview';
            render();
            
        } catch (error) {
            err.textContent = error.message;
            err.style.display = 'block';
            btn.disabled = false;
            btn.textContent = 'تسجيل الدخول ←';
        }
    });
};

// 2. استدعاء الدالة فوراً لاستبدال الصفحة التجريبية عند تحميل الموقع
login();
