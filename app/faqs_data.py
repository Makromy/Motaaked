# ==============================================================================
# Built-in Q&A Knowledge Base extracted from DEVELOPER_INTEGRATION_GUIDE.md
# Guaranteed to be available in all Docker, VPS, and standalone deployments.
# ==============================================================================

BUILTIN_GUIDE_FAQS = [
  {
    "id": 1,
    "title": "Can I use any phone to set up the SMS Forwarder app? / هل يمكنني استخدام أي هاتف لتثبيت تطبيق تحويل الرسائل؟",
    "q_en": "Can I use any phone to set up the SMS Forwarder app?",
    "q_ar": "هل يمكنني استخدام أي هاتف لتثبيت تطبيق تحويل الرسائل؟",
    "answer_en": "You must have an **Android** phone to be able to set up the SMS Forwarder app. It is a lightweight, open-source application with its download link available directly in the portal dashboard. Because it is installed from outside Google Play, you must enable installation from unknown sources, grant SMS read permissions, and set Battery Optimization to **Unrestricted** (\"Don't Optimize\").",
    "answer_ar": "يجب أن يكون لديك هاتف يعمل بنظام **Android** حتى تتمكن من إعداد تطبيق SMS Forwarder. وهو تطبيق خفيف مفتوح المصدر يتوفر رابطه المباشر داخل لوحة تحكم المنصة. ونظراً لتثبيته من خارج متجر Google Play، يجب الموافقة على تثبيت التطبيقات من مصادر غير معروفة، ومنح صلاحيات قراءة الرسائل، واستثناء التطبيق من موفر الطاقة (Battery Optimization -> Unrestricted)."
  },
  {
    "id": 2,
    "title": "Does this portal read all the SMS messages on my phone? / هل تقرأ البوابة جميع رسائل الـ SMS على هاتفي؟",
    "q_en": "Does this portal read all the SMS messages on my phone?",
    "q_ar": "هل تقرأ البوابة جميع رسائل الـ SMS على هاتفي؟",
    "answer_en": "No. Motaaked does **NOT** have direct access to your phone or your general SMS inbox. The portal receives only the specific messages that your phone forwarder app pushes via encrypted webhook. To ensure complete privacy, configure the forwarder with sender rules (e.g. sender: `\"CIB\"`, `\"NBE\"`, `\"BM\"`, `\"QNB\"`) and a text filter (e.g. `\"IPN inward transfer\"` or `\"تم تحويل\"`). Only matching incoming bank payment notifications are dispatched to the portal.",
    "answer_ar": "لا، البوابة **لا تقرأ جميع رسائل الـ SMS** الموجودة على هاتفك. البوابة تستقبل فقط الرسائل التي يقوم تطبيق التحويل بإرسالها إليها مشفرة عبر الـ Webhook، ولا تملك أي صلاحية للوصول المباشر إلى هاتفك. لحماية خصوصيتك التامة، قم بضبط فلتر الرسائل داخل التطبيق: حدد اسم أو رقم المرسل (مثل CIB أو NBE) وأضف فلتر نصي دقيق (مثل `\"IPN inward transfer\"` أو `\"تم تحويل\"`). بهذه الطريقة، يتم إرسال إشعارات المعاملات البنكية المطلوبة فقط."
  },
  {
    "id": 3,
    "title": "What should I do if my bank is not listed in active banks? / ماذا أفعل إذا لم يكن بنكي مدرجاً في قائمة البنوك المدعومة؟",
    "q_en": "What should I do if my bank is not listed in active banks?",
    "q_ar": "ماذا أفعل إذا لم يكن بنكي مدرجاً في قائمة البنوك المدعومة؟",
    "answer_en": "You can easily open a Support / Dispute Ticket from the portal's Support Hub and paste an exact sample of the incoming bank SMS message. The system administrator will configure the regular expression template in Tab 4 (Bank Patterns) to recognize your bank instantly without needing any system redeployment.",
    "answer_ar": "يمكنك فتح تذكرة دعم فني بسهولة من مركز المساعدة (Support Hub) وإرفاق نص تجريبي لرسالة البنك المستلمة. ستقوم الإدارة بإضافة قالب التعبير النمطي (Regex Pattern) الخاص ببنكك فورياً من لوحة التحكم في تبويب قوالب البنوك دون الحاجة لتحديث الكود أو إعادة تشغيل الخادم."
  },
  {
    "id": 4,
    "title": "What should I do if a transaction does not appear on Live Stream? / ماذا أفعل إذا لم تظهر المعاملة في البث المباشر؟",
    "q_en": "What should I do if a transaction does not appear on Live Stream?",
    "q_ar": "ماذا أفعل إذا لم تظهر المعاملة في البث المباشر؟",
    "answer_en": "First, check if your Android forwarder phone is connected to the internet. If the phone was temporarily offline, ensure it reconnects to Wi-Fi or cellular; all buffered unread SMS alerts will automatically synchronize. If the payment still hasn't appeared, you can enter the Bank SMS Reference ID manually in Tab 1 (Live Tracker); it will be monitored in the Pending Watchlist for up to 30 minutes until matched.",
    "answer_ar": "أولاً، تأكد من اتصال هاتف التحويل بالإنترنت؛ إذا كان الهاتف غير متصل، بمجرد إعادة الاتصال بالشبكة ستتم مزامنة كافة الرسائل غير المقروءة تلقائياً. إذا لم تظهر المعاملة بعد ذلك، يمكنك البحث عنها يدوياً بإدخال رقم مرجع رسالة البنك في تبويب المراقبة (Tab 1)، وستظل في قائمة الانتظار (Watchlist) لمدة تصل إلى 30 دقيقة حتى اكتمال المطابقة."
  },
  {
    "id": 5,
    "title": "How does automated InstaPay verification work? / كيف تعمل المطابقة والتحقق الآلي في إنستاباي؟",
    "q_en": "How does automated InstaPay verification work?",
    "q_ar": "كيف تعمل المطابقة والتحقق الآلي في إنستاباي؟",
    "answer_en": "When a customer transfers funds via InstaPay to your merchant handle, your receiving bank issues an official incoming credit SMS. The Android forwarder dispatches the alert to Motaaked within seconds. When the customer submits their order or checkout form with their Bank SMS Reference ID, Motaaked matches the reference ID and exact amount within a 30-minute sliding window, marks the credit as claimed, and instantly confirms the order.",
    "answer_ar": "عند قيام العميل بالتحويل عبر تطبيق إنستاباي إلى عنوان التاجر، يرسل بنك التاجر رسالة نصية فورية تفيد بدخول المبلغ. يمرر هاتف التحويل الرسالة إلى البوابة خلال ثوانٍ. وعند إدخال العميل لرقم المرجع في صفحة الدفع، يقوم النظام بمطابقة رقم المرجع والمبلغ بدقة متناهية خلال نافذة 30 دقيقة، وتثبيت المعاملة كمدفوعة وتفعيل الطلب آلياً بدون أي تدخل يدوي."
  },
  {
    "id": 6,
    "title": "Where can the customer find the Bank SMS Reference ID vs the InstaPay screenshot? / أين يجد العميل رقم المرجع البنكي مقارنة بلقطة شاشة إنستاباي؟",
    "q_en": "Where can the customer find the Bank SMS Reference ID vs the InstaPay screenshot?",
    "q_ar": "أين يجد العميل رقم المرجع البنكي مقارنة بلقطة شاشة إنستاباي؟",
    "answer_en": "After completing a transfer in the official InstaPay app, a green success receipt is displayed with a reference number, and the customer also receives an SMS from their bank with an official Bank Reference ID. **Crucial Distinction**: Motaaked strictly uses the **Bank SMS Reference ID**, NOT the screenshot transaction number. Screenshots are easily faked or duplicated; the Bank SMS Reference ID directly reconciles with bank statements and guarantees 100% fraud immunity.",
    "answer_ar": "بعد إتمام التحويل، يظهر للعميل إيصال أخضر في تطبيق إنستاباي، كما تصل رسالة نصية SMS من بنكه تحتوي على رقم المرجع البنكي. **تنبيه حاسم**: تعتمد منصة متأكد حصرياً على **رقم المرجع الوارد في رسالة البنك SMS**، وليس الرقم الظاهر في لقطة شاشة تطبيق إنستاباي (Screenshot)، لأن لقطات الشاشة قابلة للتزوير والتكرار، بينما رقم مرجع الرسالة النصية مطابق بنسبة 100% لكشف الحساب البنكي الرسمي ويمنع الاحتيال تماماً."
  },
  {
    "id": 7,
    "title": "How do I integrate Motaaked with WooCommerce, Shopify, or custom platforms? / كيف أربط منصة متأكد مع ووكومرس أو شوبيفاي أو المنصات المخصصة؟",
    "q_en": "How do I integrate Motaaked with WooCommerce, Shopify, or custom platforms?",
    "q_ar": "كيف أربط منصة متأكد مع ووكومرس أو شوبيفاي أو المنصات المخصصة؟",
    "answer_en": "Download official ready-to-use plugins from the Plugins Hub: for WordPress/WooCommerce and LearnDash, upload the zip plugin into WordPress admin; for Shopify, use our Draft Orders integration and liquid modal; for Laravel, Node.js, React, and Python, install our lightweight, zero-dependency SDKs. For any other custom website, embed our 2-line Drop-In Checkout Modal (`motaaked-checkout.js`).",
    "answer_ar": "يمكنك تحميل حزم وإضافات الربط الجاهزة من قسم حزم التكامل (Plugins Hub): لمتاجر ووكومرس وليرنداش ارفع ملف الـ ZIP مباشرة في لوحة ووردبريس؛ ولمتاجر شوبيفاي استخدم حزمة مسودات الطلبات؛ ولمشاريع Laravel و Node.js و React و Python استخدم حزم الـ SDK المعتمدة. ولأي موقع أو سلة شراء مخصصة أخرى، يكفي تضمين نافذة الدفع السريع المدمجة بسطرين كود فقط (`motaaked-checkout.js`)."
  },
  {
    "id": 8,
    "title": "How can I integrate Motaaked with my E-Commerce store (WooCommerce, Shopify, Laravel, etc.)? / كيف يمكنني ربط متجري الإلكتروني مع منصة متأكد؟",
    "q_en": "How can I integrate Motaaked with my E-Commerce store (WooCommerce, Shopify, Laravel, etc.)?",
    "q_ar": "كيف يمكنني ربط متجري الإلكتروني مع منصة متأكد؟",
    "answer_en": "You can integrate Motaaked into any platform using turnkey plugins and SDKs: \n  1. **WooCommerce**: Native WordPress gateway with automated status updates (`Processing`/`Completed`) and HPOS compatibility.\n  2. **Universal Drop-In Widget**: Add 2 lines of JavaScript (`motaaked-checkout.js`) to any checkout page for an instant popup modal.\n  3. **Shopify**: Integration via Draft Orders API and a Liquid checkout modal snippet.\n  4. **Framework SDKs**: Turnkey libraries for Laravel, Node.js/Express, React/Next.js, Python, and pure PHP.",
    "answer_ar": "يمكنك ربط منصة متأكد بأي متجر إلكتروني باستخدام إضافاتنا ومكتباتنا البرمجية الجاهزة:\n  1. **ووكومرس**: إضافة ووردبريس متكاملة لتحديث حالة الطلبات آلياً مع دعم كامل لنظام التخزين عالي الأداء (HPOS).\n  2. **نافذة الدفع السريع (Universal Drop-In Widget)**: إضافة سطرين فقط من كود JavaScript (`motaaked-checkout.js`) لأي صفحة دفع لفتح نافذة منبثقة عصرية.\n  3. **شوبيفاي**: ربط سلس عبر واجهة مسودات الطلبات (Draft Orders API) وقالب Liquid.\n  4. **حزم برمجية مخصصة**: لأطر عمل Laravel، Node.js، React/Next.js، بايثون، وPHP."
  },
  {
    "id": 9,
    "title": "How can I build and customize an E-Commerce checkout flow using the REST API? / كيف يمكنني بناء وتخصيص مسار الدفع الإلكتروني عبر الـ REST API؟",
    "q_en": "How can I build and customize an E-Commerce checkout flow using the REST API?",
    "q_ar": "كيف يمكنني بناء وتخصيص مسار الدفع الإلكتروني عبر الـ REST API؟",
    "answer_en": "Building a custom checkout requires just 2 API steps:\n  1. Call `POST /v1/orders/create` with your Merchant API Key (`X-API-Key`), `order_id`, and `amount` to register the pending order.\n  2. On your checkout UI, display your InstaPay IPA handle and an input field for the customer's Bank SMS Reference ID.\n  3. When the customer submits the form, call `POST /v1/orders/verify`. If matched, `verified: true` is returned, allowing you to instantly fulfill the order, unlock downloads, or deliver goods.",
    "answer_ar": "يمكنك بناء مسار دفع مخصص بخطوتين فقط عبر الـ API:\n  1. إرسال طلب `POST /v1/orders/create` يحتوي على مفتاح التاجر (`X-API-Key`) ورقم الطلب والمبلغ لتسجيل الطلب المعلق.\n  2. عرض عنوان إنستاباي الخاص بك في صفحة الشراء مع حقل مخصص لإدخال الرقم المرجعي للرسالة النصية SMS المستلمة من البنك.\n  3. عند ضغط العميل على تأكيد الدفع، استدعِ `POST /v1/orders/verify` ليقوم النظام بمطابقة العملية فوراً. إذا تمت المطابقة، تُرجع البوابة `verified: true` لتتمكن من تسليم الطلب فورياً."
  },
  {
    "id": 10,
    "title": "How does the Universal 2-Line Drop-In Checkout Widget work for E-Commerce? / كيف تعمل نافذة الدفع السريع المدمجة (سطرين كود) للتجارة الإلكترونية؟",
    "q_en": "How does the Universal 2-Line Drop-In Checkout Widget work for E-Commerce?",
    "q_ar": "كيف تعمل نافذة الدفع السريع المدمجة (سطرين كود) للتجارة الإلكترونية؟",
    "answer_en": "The Universal Drop-In Widget (`motaaked-checkout.js`) is a zero-dependency JavaScript SDK that works with any CMS, website, or framework. Simply include `<script src=\"/static/js/motaaked-checkout.js\"></script>` and trigger `MotaakedCheckout.open({ sessionToken: '...', onSuccess: (res) => { ... } })`. It opens a sleek, mobile-responsive modal overlay with a 15-minute countdown, InstaPay handle copy button, Bank SMS Reference ID validation, and real-time verification polling.",
    "answer_ar": "نافذة الدفع السريع (`motaaked-checkout.js`) هي مكتبة JavaScript مستقلة تماماً بدون أي مكتبات خارجية تعمل مع أي متجر أو موقع أو قالب. ما عليك سوى تضمين ملف السكريبت ثم استدعاء `MotaakedCheckout.open` مع رمز الجلسة والدوال المرجعية عند النجاح. تفتح النافذة واجهة منبثقة متجاوبة وعصرية تحتوي على عد تنازلي مدته 15 دقيقة، زر لنسخ عنوان التحويل، حقل إدخال الرقم المرجعي لرسالة البنك SMS، وفحص آلي دوري حتى تأكيد الدفع."
  },
  {
    "id": 11,
    "title": "Why does Motaaked verify the Bank SMS Reference ID instead of the InstaPay screenshot? / لماذا تعتمد منصة متأكد على رقم المرجع البنكي بدلاً من لقطة شاشة إنستاباي؟",
    "q_en": "Why does Motaaked verify the Bank SMS Reference ID instead of the InstaPay screenshot?",
    "q_ar": "لماذا تعتمد منصة متأكد على رقم المرجع البنكي بدلاً من لقطة شاشة إنستاباي؟",
    "answer_en": "Motaaked's zero-trust automated matching engine operates by ingesting official, cryptographic bank SMS alerts forwarded in real time from your merchant device. App screenshots can be easily faked, photoshopped, or reused. Furthermore, banks assign their own unique internal transaction reference numbers in the SMS that directly reconcile with bank statements. Matching the SMS Reference ID guarantees 100% fraud prevention and instant, tamper-proof verification.",
    "answer_ar": "يعتمد محرك التحقق الآلي في منصة متأكد على استقبال ومعالجة رسائل البنك النصية الرسمية الواردة إلى هاتف التاجر لحظياً. لقطات الشاشة للتطبيقات قابلة للتزييف أو التعديل بالفوتوشوب أو التكرار الاحتيالي. بالإضافة إلى ذلك، تصدر البنوك أرقاماً مرجعية فريدة لكل تحويل في رسائلها النصية تتطابق مباشرة مع كشف الحساب البنكي. التحقق عبر الرقم المرجعي للرسالة النصية SMS يضمن منع الاحتيال بنسبة 100% وتأكيداً لحظياً موثوقاً."
  },
  {
    "id": 12,
    "title": "How does the Drop-In Modal widget handle network latency or delayed bank SMS? / كيف تتعامل نافذة الدفع المدمجة مع بطء شبكات الاتصالات أو تأخر رسائل البنك؟",
    "q_en": "How does the Drop-In Modal widget handle network latency or delayed bank SMS?",
    "q_ar": "كيف تتعامل نافذة الدفع المدمجة مع بطء شبكات الاتصالات أو تأخر رسائل البنك؟",
    "answer_en": "During bank rush hours, bank SMS messages may experience 10 to 45 seconds of telecom delivery delay. The Drop-In Modal widget (`motaaked-checkout.js`) features built-in automated polling. When a customer enters their Bank SMS Reference ID, the widget polls `/v1/orders/verify` every 3 to 4 seconds for up to 20 attempts while displaying an active countdown timer. As soon as the SMS arrives and is ingested, the modal automatically transitions to success and redirects the customer.",
    "answer_ar": "في أوقات الذروة البنكية، قد تتأخر رسالة البنك النصية من 10 إلى 45 ثانية بسبب شبكات الاتصالات. تحتوي نافذة الدفع المدمجة (`motaaked-checkout.js`) على نظام استعلام آلي مدمج؛ حيث تقوم بطلب التحقق من الخادم كل 3 إلى 4 ثوانٍ لما يصل إلى 20 محاولة مع إظهار عداد زمني للعميل. وبمجرد وصول رسالة البنك ومطابقتها، تتحول النافذة فورياً لشاشة النجاح وتوجيه العميل لصفحة الشكر."
  },
  {
    "id": 13,
    "title": "What happens if a customer transfers an incorrect amount (underpayment / overpayment)? / ماذا يحدث إذا حول العميل مبلغاً غير مطابق (مبلغ منقوص أو زائد)؟",
    "q_en": "What happens if a customer transfers an incorrect amount (underpayment",
    "q_ar": "overpayment)?",
    "answer_en": "Motaaked enforces exact-amount matching with zero tolerance. If an order expects `250.00 EGP` and the customer transfers `240.00 EGP`, the payment will **NOT** be matched to the order, preventing underpayment fraud. The incoming credit remains marked as `UNCLAIMED` in your merchant dashboard, where your staff can review it or assign it manually.",
    "answer_ar": "تطبق المنصة سياسة المطابقة التامة للمبلغ بدون تساهل. إذا كان إجمالي الطلب `250.00 ج.م` وحول العميل `240.00 ج.م`، فلن تتم مطابقة العملية للطلب تفادياً للاحتيال وسداد مبالغ منقوصة. تظل المعاملة مسجلة في لوحة تحكم التاجر بحالة غير مطالب بها (`UNCLAIMED`) ليتمكن فريق العمل من مراجعتها أو ربطها يدوياً."
  },
  {
    "id": 14,
    "title": "Can the same Bank SMS Reference ID be used twice for different orders (Replay Attacks)? / هل يمكن استخدام نفس رقم المرجع البنكي مرتين لطلبين مختلفين (الحماية من التكرار)؟",
    "q_en": "Can the same Bank SMS Reference ID be used twice for different orders (Replay Attacks)?",
    "q_ar": "هل يمكن استخدام نفس رقم المرجع البنكي مرتين لطلبين مختلفين (الحماية من التكرار)؟",
    "answer_en": "No. All matches are completely atomic. When an incoming credit is matched to an order, its state is immediately committed as `CLAIMED` in the database within a serializable database transaction. Subsequent verification attempts with the same reference ID will be rejected as already claimed, preventing replay attacks and double-spending.",
    "answer_ar": "لا. كافة عمليات المطابقة تتم بشكل ذري وآمن تماماً (`Atomic Transaction`). بمجرد تأكيد مطابقة رسالة البنك لطلب معين، تتغير حالتها فورياً في قاعدة البيانات إلى مستهلكة (`CLAIMED`). وأي محاولة لاحقة لاستخدام نفس رقم المرجع لطلب آخر تُرفض فوراً لمنع هجمات إعادة الاستخدام والاحتيال المزدوج (`Double-Spending`)."
  },
  {
    "id": 15,
    "title": "How do I handle inventory reservation in WooCommerce or Shopify during payment? / كيف أتعامل مع حجز المخزون في ووكومرس أو شوبيفاي أثناء الدفع؟",
    "q_en": "How do I handle inventory reservation in WooCommerce or Shopify during payment?",
    "q_ar": "كيف أتعامل مع حجز المخزون في ووكومرس أو شوبيفاي أثناء الدفع؟",
    "answer_en": "In WooCommerce, orders created with InstaPay are placed in `Pending payment` status with WooCommerce's built-in hold stock timer (e.g. 15 minutes). When Motaaked verifies the Bank SMS Reference ID, the order moves to `Processing` or `Completed`, permanently deducting inventory. If the customer abandons the checkout without paying within 15 minutes, WooCommerce automatically cancels the order and restores the inventory.",
    "answer_ar": "في ووكومرس، يتم وضع الطلبات التي تختار الدفع بإنستاباي في حالة `Pending payment` (قيد انتظار الدفع) مع تفعيل مؤقت حجز المخزون الافتراضي لووكومرس (مثلاً 15 دقيقة). وبمجرد تأكيد الدفع عبر متأكد، ينتقل الطلب لحالة قيد التنفيذ أو مكتمل ويتم خصم المخزون نهائياً. وإذا تراجع العميل ولم يسدد خلال المهلة، يُلغى الطلب آلياً ويعود المخزون لحالته."
  },
  {
    "id": 16,
    "title": "What if the merchant's Android forwarder phone loses Wi-Fi connection or battery? / ماذا يحدث إذا فقد هاتف التحويل الاتصال بالإنترنت أو نفدت بطاريته؟",
    "q_en": "What if the merchant's Android forwarder phone loses Wi-Fi connection or battery?",
    "q_ar": "ماذا يحدث إذا فقد هاتف التحويل الاتصال بالإنترنت أو نفدت بطاريته؟",
    "answer_en": "If the forwarder phone temporarily loses Wi-Fi or battery, the Android SMS inbox continues receiving SMS alerts from the telecom carrier. As soon as the device reconnects to Wi-Fi or cellular data, the forwarder application immediately catches up and dispatches all unread bank SMS messages in chronological order. Pending orders that were awaiting verification will be matched instantly upon reconnection.",
    "answer_ar": "إذا فقد هاتف التحويل الاتصال بالإنترنت أو نفدت بطاريته مؤقتاً، يستمر صندوق رسائل الهاتف في استقبال رسائل البنك عبر شبكة المحمول بدون توقف. وبمجرد إعادة توصيل الهاتف بالإنترنت، يقوم التطبيق بمزامنة وإرسال كافة الرسائل المتراكمة بالترتيب الزمني فوراً، وتتم مطابقة كافة الطلبات المعلقة فورياً عند إعادة الاتصال."
  },
  {
    "id": 17,
    "title": "Can multiple branch cashiers or multiple websites share the same Motaaked gateway? / هل يمكن لعدة كاشيرات في الفروع أو عدة مواقع مشاركة نفس بوابة متأكد؟",
    "q_en": "Can multiple branch cashiers or multiple websites share the same Motaaked gateway?",
    "q_ar": "هل يمكن لعدة كاشيرات في الفروع أو عدة مواقع مشاركة نفس بوابة متأكد؟",
    "answer_en": "Yes. Motaaked includes a complete Multi-User & Multi-Key system. You can generate distinct API keys for your WooCommerce store, your Shopify store, your mobile app, and individual retail POS cashiers. Each transaction tracks the originating merchant and API key for full accounting isolation.",
    "answer_ar": "نعم. تشتمل منصة متأكد على منظومة متعددة المستخدمين ومفاتيح الـ API. يمكنك إنشاء مفاتيح ربط مستقلة لكل متجر من متاجرك (ووكومرس، شوبيفاي، تطبيق الموبايل، أو كاشيرات الفروع). ويتم تسجيل كل معاملة مع مفتاح الربط والتاجر التابع له لعزل الحسابات والتقارير المالية بدقة."
  },
  {
    "id": 18,
    "title": "How do I test the entire e-commerce checkout flow in local development? / كيف أختبر دورة الدفع الكاملة للتجارة الإلكترونية في بيئة التطوير المحلية؟",
    "q_en": "How do I test the entire e-commerce checkout flow in local development?",
    "q_ar": "كيف أختبر دورة الدفع الكاملة للتجارة الإلكترونية في بيئة التطوير المحلية؟",
    "answer_en": "In development mode (`http://localhost:8000`), you can simulate incoming bank SMS alerts via the Merchant Dashboard's **Test Drop-In Modal** or by calling `POST /webhook` with a simulated SMS text (e.g., `\"تم تحويل مبلغ 100.00 جم إلى حسابكم بنجاح. رقم المرجع: 240923000999\"`). Then run your checkout flow and input `240923000999` to see real-time verification and fulfillment.",
    "answer_ar": "في بيئة التطوير المحلية (`http://localhost:8000`)، يمكنك محاكاة رسائل البنك الواردة من خلال زر **تجربة نافذة الدفع (Test Drop-In Modal)** في لوحة التاجر، أو عبر إرسال طلب `POST /webhook` بنص رسالة بنكية تجريبية (مثال: `\"تم تحويل مبلغ 100.00 جم إلى حسابكم بنجاح. رقم المرجع: 240923000999\"`). بعد ذلك، قم بتجربة الدفع وإدخال رقم المرجع `240923000999` لتشاهد التحقق والتأكيد اللحظي للطلب."
  },
  {
    "id": 19,
    "title": "What is Live Stream and how does it work? / ما هو البث المباشر (Live Stream) وكيف يعمل؟",
    "q_en": "What is Live Stream and how does it work?",
    "q_ar": "ما هو البث المباشر (Live Stream) وكيف يعمل؟",
    "answer_en": "Live Stream (Tab 1 in your dashboard) is a real-time monitor that displays incoming bank transfer SMS messages the exact moment they are pushed from your forwarder phone. Each card reveals the received amount, timestamp, originating bank, sending party, and current claim status (UNCLAIMED or CLAIMED). It gives store owners and branch cashiers a live, transparent window into incoming payments as they happen without having to manually check their phone or bank app.",
    "answer_ar": "البث المباشر (Live Stream) في التبويب الأول هو شاشة مراقبة لحظية تعرض إشعارات ورسائل البنك فور وصولها من هاتف التحويل. توضح كل بطاقة معاملة: المبلغ المستلم، وقت وتاريخ المعاملة، البنك المستلم، وحالة المطالبة (غير مطالب بها / UNCLAIMED أو تمت المطالبة / CLAIMED). يتيح ذلك لأصحاب المتاجر وكاشيرات الفروع رؤية التحويلات الواردة لحظة بلحظة دون الحاجة لفتح هاتف التحويل أو تطبيق البنك."
  },
  {
    "id": 20,
    "title": "How can I make a manual search for a Reference ID? / كيف أقوم بالبحث اليدوي عن رقم المرجع (Manual Reference Search)؟",
    "q_en": "How can I make a manual search for a Reference ID?",
    "q_ar": "كيف أقوم بالبحث اليدوي عن رقم المرجع (Manual Reference Search)؟",
    "answer_en": "To perform a Manual Search, navigate to Tab 1 (Live Tracker & Watchlist) or Tab 2 (Audit Explorer). Enter the 12-digit Bank SMS Reference ID provided by the customer into the Reference ID search box and click Search. The system queries the bank credits database; if found, it immediately displays the transaction details, verification status, and bank timestamp. If the SMS has not yet arrived due to telecom delay, the system automatically places it into the Pending Watchlist to monitor it live for up to 30 minutes without needing to re-enter it. Each manual search deducts 1 search credit from your active wallet balance.",
    "answer_ar": "لإجراء البحث اليدوي (Manual Search)، توجه إلى التبويب الأول (المراقبة الحية) أو التبويب الثاني (سجل المعاملات). اكتب رقم المرجع البنكي (12 رقماً) الذي يقدمه العميل في خانة البحث ثم اضغط على زر فحص المرجع. يقوم النظام بالبحث في قاعدة بيانات رسائل البنك فوراً؛ وإذا وُجدت الرسالة، تظهر تفاصيل العملية وحالتها ووقت وصولها. وإذا لم تكن الرسالة قد وصلت بعد بسبب تأخر شبكات الاتصالات، يُسجل الرقم تلقائياً في قائمة الانتظار (Watchlist) لمراقبته آلياً لمدة 30 دقيقة بمجرد وصوله. يخصم كل بحث يدوي نقطة واحدة (1 Credit) من رصيد محفظتك النشط."
  },
  {
    "id": 21,
    "title": "What is the charging and credit deduction mechanism? / ما هي آلية خصم النقاط والرسوم (Charging Mechanism)؟",
    "q_en": "What is the charging and credit deduction mechanism?",
    "q_ar": "ما هي آلية خصم النقاط والرسوم (Charging Mechanism)؟",
    "answer_en": "Motaaked utilizes a fair, transparent Waterfall Credit Deduction model for payment verification: 1. 1 Verification / Search = 1 Credit: Deducted only upon verifying an order or executing a manual reference search. 2. Waterfall Deduction Hierarchy: The platform first consumes your Free Monthly Tier Credits (renewed on the 1st of each month). If a Day Pass is active, all searches are 100% free and unlimited. Next, it consumes any active Promotional / Top-Up Wallet Credits. 3. No Fees on Payments: InstaPay and IPN network transfers have 0% transaction fees from the Central Bank of Egypt. Motaaked does not take any percentage cut of your transaction money.",
    "answer_ar": "تعتمد منصة متأكد على نموذج المحفظة الشلالية (Waterfall Deduction Model) العادل والشفاف: 1. 1 عملية فحص أو تحقق = 1 نقطة (Credit): تُخصم فقط عند التحقق من طلب دفع أو إجراء بحث يدوي عن رقم المرجع. 2. ترتيب الخصم الشلالي: يستهلك النظام أولاً النقاط الشهرية المجانية (التي تتجدد تلقائياً أول كل شهر ميلادي). وفي حال تفعيل تذكرة اليوم غير المحدود (Day Pass) تكون جميع العمليات مجانية وغير محدودة. وبعدها يتم الخصم من رصيد باقات الشحن الترويجية. 3. صفر عمولات على التحويلات: شبكة إنستاباي القومية مجانية بنسبة 0% وبدون عمولات من البنك المركزي المصري، ولا تقتطع منصة متأكد أي نسبة مئوية من أموال معاملاتك."
  },
  {
    "id": 22,
    "title": "How can we recharge our balance and buy credit packages? / كيف يمكننا شحن الرصيد وشراء باقات النقاط (Recharge / Top-Up)؟",
    "q_en": "How can we recharge our balance and buy credit packages?",
    "q_ar": "كيف يمكننا شحن الرصيد وشراء باقات النقاط (Recharge / Top-Up)؟",
    "answer_en": "To recharge your credit balance: 1. Navigate to Tab 3 (Packages & Top-Up / شحن الرصيد) in your merchant dashboard. 2. Select your desired package (e.g. Starter, Pro, or Enterprise) and click Recharge. 3. The platform displays an automated invoice with the portal's official InstaPay IPA handle and the exact required amount. 4. Open your InstaPay app, transfer the exact amount, and copy the Bank SMS Reference ID received on your phone. 5. Paste the Reference ID into the invoice confirmation box and click Verify Payment. 6. The platform's automated engine verifies the transfer instantly and activates your credits immediately 24/7. Alternatively, if your administrator issued a prepaid voucher code, enter it under Redeem Voucher to top up instantly.",
    "answer_ar": "لشحن رصيد محفظتك وشراء باقات النقاط: 1. توجه إلى التبويب الثالث (باقات الشحن / Packages & Top-Up) في لوحة التحكم. 2. اختر الباقة المناسبة لاحتياجاتك (مثلاً: Starter أو Pro أو Enterprise) واضغط على شحن الرصيد. 3. تُظهر المنصة فاتورة سداد فورية تحتوي على عنوان إنستاباي المعتمد للمنصة والمبلغ المطلوب بدقة. 4. افتح تطبيق إنستاباي على هاتفك، وقم بتحويل المبلغ، ثم انسخ رقم المرجع البنكي من رسالة البنك النصية SMS التي تصلك. 5. الصق رقم المرجع في خانة تأكيد الفاتورة واضغط تأكيد الدفع. 6. يتحقق محرك النظام من التحويل آلياً ويقوم بتفعيل النقاط في محفظتك فوراً على مدار الساعة (24/7). كما يمكنك أيضاً شحن رصيدك إذا كان لديك كود قسيمة مسبقة الدفع بإدخاله في قسم شحن عبر قسيمة (Redeem Voucher)."
  },
  {
    "id": 23,
    "title": "What do you mean by Validity and when do credits expire? / ماذا تعني فترة الصلاحية (Validity Period) ومتى تنتهي النقاط؟",
    "q_en": "What do you mean by Validity and when do credits expire?",
    "q_ar": "ماذا تعني فترة الصلاحية (Validity Period) ومتى تنتهي النقاط؟",
    "answer_en": "Validity Period defines the active lifespan of purchased credits and merchant accounts: 1. Package Validity: When you purchase a top-up package, it includes a defined validity duration (e.g., 30, 90, or 365 days). All purchased credits remain usable until that date. 2. Free Monthly Tier: Resets on the 1st day of every calendar month at 00:00 UTC. Unused free tier credits do not roll over to the next month. 3. Day Pass Unlimited: Grants 24 consecutive hours of unlimited searches from the exact second of activation. 4. Expiration Monitoring: Your active expiration date is prominently displayed on your top dashboard badge. If validity expires, you can simply purchase any package or redeem a voucher to instantly reactivate your wallet balance.",
    "answer_ar": "فترة الصلاحية (Validity Period) هي المدة الزمنية المحددة التي تظل فيها نقاطك وحسابك نشطاً وقابلاً للاستخدام: 1. صلاحية باقات الشحن: عند شراء باقة نقاط، يكون لها مدة صلاحية محددة (مثل 30 أو 90 أو 365 يوماً). تظل كافة النقاط المشتراة صالحة للاستخدام حتى تاريخ الانتهاء. 2. النقاط الشهرية المجانية: تتجدد تلقائياً في اليوم الأول من كل شهر ميلادي الساعة 00:00، ولا ترحل النقاط المجانية غير المستهلكة للشهر التالي. 3. تذكرة اليوم غير المحدود (Day Pass): تمنحك 24 ساعة متواصلة من عمليات البحث والتحقق غير المحدودة تبدأ من لحظة التفعيل. 4. متابعة الصلاحية: يظهر تاريخ انتهاء الصلاحية بوضوح في الشارة أعلى لوحة التحكم. وإذا انتهت الصلاحية، يكفي شراء أي باقة أو تفعيل قسيمة شحن لإعادة تفعيل رصيدك فورياً."
  },
  {
    "id": 24,
    "title": "How can I activate SMS Push / Webhook Ingestion? / كيف أقوم بتفعيل إرسال الرسائل الفوري (SMS Push / Webhook)؟",
    "q_en": "How can I activate SMS Push / Webhook Ingestion?",
    "q_ar": "كيف أقوم بتفعيل إرسال الرسائل الفوري (SMS Push / Webhook)؟",
    "answer_en": "To activate automated SMS Push from your Android forwarder device: 1. Open the SMS Forwarder application on your dedicated forwarder phone. 2. Go to Settings / Rules and add a Webhook (HTTP POST) destination. 3. Set the Destination URL to your portal's webhook endpoint: https://your-domain.com/webhook (e.g., https://insta.saf7etna.dpdns.org/webhook). 4. Set the Request Method to POST and format to JSON. 5. In Custom Headers, add: X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY (as configured in Tab 4 / Settings). 6. Set the JSON payload template to dispatch {\"sender\": \"[sender]\", \"message\": \"[message]\", \"timestamp\": [timestamp]}. 7. Turn on the Auto-forward incoming SMS toggle and test connection. Incoming bank credits will now push in under 2 seconds.",
    "answer_ar": "لتفعيل إرسال الرسائل اللحظي (SMS Push) من هاتف الأندرويد إلى المنصة: 1. افتح تطبيق SMS Forwarder على هاتف التحويل المخصص للخدمة. 2. انتقل إلى الإعدادات / القواعد (Rules) وأضف وجهة إرسال من نوع Webhook (HTTP POST). 3. اكتب رابط الخادم (Webhook URL) الخاص بمنصتك: https://your-domain.com/webhook (مثال: https://insta.saf7etna.dpdns.org/webhook). 4. اختر طريقة الإرسال POST وصيغة البيانات JSON. 5. في خانة Custom Headers، أضف المفتاح السري للتحويل: X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY (المحدد في إعدادات النظام في تبويب الإدارة). 6. اضبط قالب الـ JSON ليرسل المرسل والرسالة والوقت: {\"sender\": \"[sender]\", \"message\": \"[message]\", \"timestamp\": [timestamp]}. 7. فعّل خيار التحويل التلقائي عند استلام الرسائل واضغط اختبار الاتصال، وسيتم استقبال رسائل البنوك خلال أقل من ثانيتين."
  },
  {
    "id": 25,
    "title": "How can I set up the SMS Forwarder without sending all my personal SMS messages? / كيف أضبط تطبيق التحويل لحماية خصوصيتي دون إرسال جميع رسائل هاتفي؟",
    "q_en": "How can I set up the SMS Forwarder without sending all my personal SMS messages?",
    "q_ar": "كيف أضبط تطبيق التحويل لحماية خصوصيتي دون إرسال جميع رسائل هاتفي؟",
    "answer_en": "To maintain 100% personal privacy on your forwarder phone and ensure only bank payment alerts are pushed: 1. In the SMS Forwarder application, create a Dedicated Forwarding Rule rather than forwarding all SMS. 2. In the Sender Filter field, whitelist only your specific banks (e.g., CIB, NBE, BM, QNB, AAIB, BDC, AlexBank, HSBC). 3. In the Content / Text Filter field, enter incoming payment keywords: \"تم تحويل\" OR \"IPN inward transfer\" OR \"إيداع\" OR \"credited\". 4. Add an Exclusion Filter for debit/spending alerts containing \"سحب\" or \"خصم\" or \"مشتريات\" or \"debit\". 5. With these rules, personal text messages, OTP verification codes, and unrelated SMS alerts are strictly ignored by the app and are never transmitted over the internet.",
    "answer_ar": "لضمان الخصوصية التامة (100%) لهاتفك والتأكد من إرسال رسائل التحويلات البنكية فقط دون أي رسائل شخصية: 1. داخل تطبيق SMS Forwarder، قم بإنشاء قاعدة تحويل مخصصة (Specific Rule) وتجنب خيار تحويل جميع الرسائل. 2. في حقل فلتر المرسل (Sender Filter): أضف أسماء البنوك المعتمدة لديك فقط (مثل: CIB، NBE، BM، QNB، AAIB، AlexBank، HSBC). 3. في حقل فلتر نص الرسالة (Content / Text Filter): أضف الكلمات الدالة على التحويلات الواردة فقط، مثل: \"تم تحويل\" أو \"IPN inward transfer\" أو \"إيداع\" أو \"credited\". 4. أضف استثناءً لكلمات الخصم والمشتريات مثل: \"سحب\" أو \"خصم\" أو \"مشتريات\" أو \"debit\". 5. بفضل هذا الضبط، يتجاهل التطبيق تماماً أي رسائل شخصية أو رموز تحقق (OTP) أو رسائل دعائية، ولا يخرج من هاتفك سوى إشعارات الإيداع البنكية المطلوبة للمتجر.",
  },
  {
    "id": 26,
    "title": "What is the meaning of Heartbeat & how does it work? / ما هو النبض (Heartbeat) وكيف يعمل لمراقبة هاتف التحويل؟",
    "q_en": "What is the meaning of Heartbeat & how does it work?",
    "q_ar": "ما هو النبض (Heartbeat) وكيف يعمل لمراقبة هاتف التحويل؟",
    "answer_en": "Heartbeat is an automated telemetry health ping sent by the forwarder phone to Motaaked every 5 minutes: 1. What it monitors: It reports the phone's current battery percentage, charging state (plugged in or running on battery), network connection type (Wi-Fi or 4G), and forwarder background service vitality. 2. How it works: The app sends a lightweight ping to /v1/telemetry/heartbeat. Motaaked updates the forwarder telemetry badge on Tab 1 and Tab 4. 3. Zero-Downtime Alerts: If Motaaked does not receive a heartbeat for more than 15 minutes, it flags the forwarder status as WARNING or OFFLINE, alerting administrators immediately before any incoming payments are missed due to a drained battery or disconnected Wi-Fi.",
    "answer_ar": "النبض (Heartbeat) هو إشارة فحص وحالة صحية دورية يرسلها هاتف التحويل تلقائياً إلى المنصة كل 5 دقائق: 1. ماذا يراقب: يقوم بإرسال نسبة شحن البطارية الحالية، حالة الشاحن (متصل بالكهرباء أم يعمل على البطارية)، نوع شبكة الاتصال (Wi-Fi أو بيانات 4G)، واستقرار التطبيق في الخلفية. 2. كيف يعمل: يرسل التطبيق إشارة خفيفة إلى مسار /v1/telemetry/heartbeat، لتقوم المنصة بتحديث شارة حالة الهاتف في التبويب الأول والرابع فوراً. 3. الحماية من انقطاع الخدمة: إذا انقطعت إشارات النبض لأكثر من 15 دقيقة، تتغير حالة الهاتف تلقائياً إلى تحذير / WARNING أو غير متصل / OFFLINE، لتنبيه التاجر فوراً لتفقد شاحن الهاتف أو شبكة الإنترنت قبل أن تتأثر عمليات الدفع الواردة لمتجرك.",
  },
  {
    "id": 27,
    "title": "What is the Pending Watchlist and how does it protect delayed payments? / ما هي قائمة الانتظار والمراقبة (Pending Watchlist) وكيف تحمي المدفوعات المتأخرة؟",
    "q_en": "What is the Pending Watchlist and how does it protect delayed payments?",
    "q_ar": "ما هي قائمة الانتظار والمراقبة (Pending Watchlist) وكيف تحمي المدفوعات المتأخرة؟",
    "answer_en": "The Pending Watchlist (Tab 1) is a real-time monitor for orders or reference searches that were submitted before the bank SMS arrived at the merchant's phone: 1. When a customer or cashier enters a Reference ID that hasn't arrived yet, the platform registers it as a PENDING watcher for 30 minutes with an active live countdown. 2. The moment the delayed bank SMS reaches the forwarder phone, Motaaked matches the reference ID atomically, marks the transaction as MATCHED, and notifies the checkout or cashier UI in real time without requiring the user to search again.",
    "answer_ar": "قائمة الانتظار والمراقبة (Pending Watchlist) في التبويب الأول هي ميزة ذكية لمتابعة المعاملات التي أدخل العميل أو الكاشير رقم مرجعها قبل وصول رسالة البنك لهاتف التاجر: 1. عند إدخال رقم مرجع لم تصل رسالته بعد، يسجله النظام كمعاملة معلقة (PENDING) لمدة 30 دقيقة مع مؤقت تنازلي حي. 2. بمجرد وصول رسالة البنك المتأخرة لهاتف التحويل، يطابقها النظام فورياً، ويحول حالتها إلى تمت المطابقة / MATCHED ويُحدث شاشة الدفع أو الكاشير تلقائياً دون الحاجة لإعادة كتابة الرقم.",
  },
  {
    "id": 28,
    "title": "How can I export reports and financial statements? / كيف أقوم بتصدير التقارير وكشوف الحسابات المالية (CSV & PDF)؟",
    "q_en": "How can I export reports and financial statements?",
    "q_ar": "كيف أقوم بتصدير التقارير وكشوف الحسابات المالية (CSV & PDF)؟",
    "answer_en": "Motaaked allows you to export complete audit trails and accounting statements from Tab 2 (Audit Explorer / سجل المعاملات): 1. Filters: Filter your transactions by date range (e.g. today, last 7 days, this month, or custom dates), status (CLAIMED, UNCLAIMED), or specific API key / cashier. 2. Excel / CSV Export: Click Export CSV to download a clean spreadsheet with reference IDs, exact amounts, timestamps, and customer order numbers for reconciliation. 3. Official PDF Statement: Click Generate PDF Statement to download a stamped, branded financial statement with proper Arabic text rendering, total credit summary, and verification totals.",
    "answer_ar": "تتيح لك منصة متأكد تصدير تقارير محاسبية وكشوف حسابات رسمية كاملة من التبويب الثاني (سجل المعاملات / Audit Explorer): 1. تصفية المعاملات: يمكنك فلترة المعاملات حسب التاريخ (اليوم، آخر 7 أيام، هذا الشهر، أو فترة مخصصة)، أو حسب الحالة (مطالب بها / CLAIMED أو غير مطالب بها / UNCLAIMED)، أو مفتاح API / كاشير معين. 2. تصدير إكسل (CSV Export): اضغط على زر تصدير CSV لتحميل ملف جدول بيانات يحتوي على أرقام المراجع، المبالغ، التواريخ، وأرقام الطلبات لمطابقتها مع دفاتر حساباتك. 3. كشف حساب PDF رسمي: اضغط على زر كشف حساب PDF لتنزيل تقرير مالي منسق ومروس ومختوم يدعم اللغة العربية بالكامل، مع إجمالي المبالغ وعدد المعاملات الناجحة.",
  }
]
