"""
Multilingual translation module for the dental chatbot.
Supports: English (en), Arabic (ar), Urdu (ur), Tagalog (tl)
"""

from langdetect import detect, LangDetectException

SUPPORTED_LANGUAGES = {'en', 'ar', 'ur', 'tl', 'es', 'fr', 'zh'}  # English, Arabic, Urdu, Tagalog, Spanish, French, Chinese
LANGUAGE_NAMES = {
    'en': 'English',
    'ar': 'العربية',
    'ur': 'اردو',
    'tl': 'Tagalog',
    'es': 'Español',
    'fr': 'Français',
    'zh': '中文',
}


def detect_language(text):
    """Detect language from text. Returns language code or 'en' as fallback."""
    try:
        lang = detect(text)
        # Map language codes (langdetect uses ISO 639-1)
        if lang in SUPPORTED_LANGUAGES:
            return lang
        # Some mappings
        if lang == 'fil':  # Filipino/Tagalog
            return 'tl'
        if lang in ('zh-cn', 'zh-tw', 'zh'):
            return 'zh'
        return 'en'  # Unsupported → fallback to English
    except LangDetectException:
        return 'en'


# ---------------------------------------------------------------------------
# Complete translation dictionary
# ---------------------------------------------------------------------------

TRANSLATIONS = {

    # ── Booking flow ──────────────────────────────────────────────────────

    'greeting': {
        'en': "Hi! I'm your dental assistant. How can I help you today?",
        'ar': "مرحباً! أنا مساعدك لطب الأسنان. كيف يمكنني مساعدتك اليوم؟",
        'ur': "ہیلو! میں آپ کا ڈینٹل اسسٹنٹ ہوں۔ آج میں آپ کی کیسے مدد کر سکتا ہوں؟",
        'tl': "Kumusta! Ako ang iyong dental assistant. Paano kita matutulungan ngayon?",
        'es': "¡Hola! Soy tu asistente dental. ¿En qué puedo ayudarte hoy?",
        'fr': "Bonjour ! Je suis votre assistant dentaire. Comment puis-je vous aider aujourd'hui ?",
        'zh': "您好！我是您的牙科助手。今天有什么可以帮您的？",
    },

    'ask_name': {
        'en': "To get started, what's your name?",
        'ar': "للبدء، ما اسمك؟",
        'ur': "شروع کرنے کے لیے، آپ کا نام کیا ہے؟",
        'tl': "Para makapagsimula, ano ang pangalan mo?",
        'es': "Para empezar, ¿cuál es tu nombre?",
        'fr': "Pour commencer, quel est votre nom ?",
        'zh': "首先，请问您叫什么名字？",
    },

    'nice_to_meet': {
        'en': "Nice to meet you, {name}! What type of doctor would you like to see%s",
        'ar': "تشرفنا بك يا {name}! ما التخصص الذي تودّ حجز موعد فيه؟",
        'ur': "آپ سے مل کر خوشی ہوئی، {name}! آپ کس قسم کے ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Ikinagagalak kitang makilala, {name}! Anong uri ng doktor ang gusto mong puntahan%s",
        'es': "¡Encantado de conocerte, {name}! ¿Qué tipo de doctor te gustaría ver%s",
        'fr': "Ravi de vous rencontrer, {name} ! Quel type de médecin souhaitez-vous consulter%s",
        'zh': "很高兴认识你，{name}！你想看哪种类型的医生%s",
    },

    'ask_category': {
        'en': "What type of doctor would you like to see%s",
        'ar': "ما التخصص الذي تودّ حجز موعد فيه؟",
        'ur': "آپ کس قسم کے ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Anong uri ng doktor ang gusto mong puntahan%s",
        'es': "¿Qué tipo de doctor te gustaría ver%s",
        'fr': "Quel type de médecin souhaitez-vous consulter%s",
        'zh': "您想看哪种类型的医生%s",
    },

    'invalid_category': {
        'en': "I didn't recognize that specialty. Please pick one from the list:",
        'ar': "لم أتعرّف على هذا التخصص. يرجى اختيار تخصص من القائمة:",
        'ur': "مجھے یہ تخصص سمجھ نہیں آیا۔ براہ کرم فہرست میں سے ایک منتخب کریں:",
        'tl': "Hindi ko nakilala ang espesyalidad na iyon. Pumili mula sa listahan:",
        'es': "No reconocí esa especialidad. Por favor elige una de la lista:",
        'fr': "Je n'ai pas reconnu cette spécialité. Veuillez en choisir une dans la liste :",
        'zh': "我无法识别该专科。请从列表中选择一个：",
    },

    'ask_doctor': {
        'en': "Which doctor would you like to see%s",
        'ar': "أيّ طبيب تودّ زيارته؟",
        'ur': "آپ کس ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Aling doktor ang gusto mong puntahan%s",
        'es': "¿Qué doctor te gustaría ver%s",
        'fr': "Quel médecin souhaitez-vous consulter%s",
        'zh': "您想看哪位医生%s",
    },

    'invalid_doctor': {
        'en': "I didn't recognize that doctor. Please pick one from the list:",
        'ar': "لم أتعرّف على هذا الطبيب. يرجى اختيار طبيب من القائمة:",
        'ur': "مجھے یہ ڈاکٹر سمجھ نہیں آیا۔ براہ کرم فہرست میں سے ایک منتخب کریں:",
        'tl': "Hindi ko nakilala ang doktor na iyon. Pumili mula sa listahan:",
        'es': "No reconocí a ese doctor. Por favor elige uno de la lista:",
        'fr': "Je n'ai pas reconnu ce médecin. Veuillez en choisir un dans la liste :",
        'zh': "我无法识别该医生。请从列表中选择一位：",
    },

    'doctor_selected': {
        'en': "Great choice! You'll be seeing Dr. {doctor}. When would you like to come in?",
        'ar': "اختيار ممتاز! ستكون زيارتك لدى د. {doctor}. متى تودّ الحضور؟",
        'ur': "بہترین انتخاب! آپ ڈاکٹر {doctor} سے ملیں گے۔ آپ کب آنا چاہیں گے؟",
        'tl': "Magandang pagpili! Makikita mo si Dr. {doctor}. Kailan mo gustong pumunta?",
        'es': "¡Excelente elección! Verás al Dr. {doctor}. ¿Cuándo te gustaría venir?",
        'fr': "Excellent choix ! Vous verrez le Dr {doctor}. Quand souhaitez-vous venir ?",
        'zh': "很好的选择！您将看到{doctor}医生。您希望什么时候来？",
    },

    'ask_date': {
        'en': "When would you like to come in?",
        'ar': "متى تودّ الحضور؟",
        'ur': "آپ کب آنا چاہیں گے؟",
        'tl': "Kailan mo gustong pumunta?",
        'es': "¿Cuándo te gustaría venir?",
        'fr': "Quand souhaitez-vous venir ?",
        'zh': "您希望什么时候来？",
    },

    'invalid_date': {
        'en': "I couldn't understand that date. Please select a date from the calendar:",
        'ar': "لم أتمكّن من فهم التاريخ. يرجى اختيار تاريخ من التقويم:",
        'ur': "مجھے یہ تاریخ سمجھ نہیں آئی۔ براہ کرم کیلنڈر سے تاریخ منتخب کریں:",
        'tl': "Hindi ko naintindihan ang petsang iyon. Pumili ng petsa mula sa kalendaryo:",
        'es': "No pude entender esa fecha. Por favor selecciona una del calendario:",
        'fr': "Je n'ai pas compris cette date. Veuillez sélectionner une date dans le calendrier :",
        'zh': "我无法理解该日期。请从日历中选择一个日期：",
    },

    'weekend_closed': {
        'en': "We're closed on weekends. Please pick a weekday:",
        'ar': "العيادة مغلقة في عطلة نهاية الأسبوع. يرجى اختيار يوم عمل:",
        'ur': "ہم ہفتے کے آخر میں بند رہتے ہیں۔ براہ کرم کوئی ورکنگ ڈے منتخب کریں:",
        'tl': "Sarado kami tuwing weekend. Pumili ng weekday:",
        'es': "Estamos cerrados los fines de semana. Por favor elige un día entre semana:",
        'fr': "Nous sommes fermés le week-end. Veuillez choisir un jour de semaine :",
        'zh': "我们周末不营业。请选择工作日：",
    },

    'ask_time': {
        'en': "What time works best for you%s",
        'ar': "ما الوقت الأنسب لك؟",
        'ur': "آپ کے لیے کون سا وقت مناسب ہے؟",
        'tl': "Anong oras ang pinakamaginhawa para sa iyo?",
        'es': "¿Qué hora te conviene mejor%s",
        'fr': "Quelle heure vous convient le mieux%s",
        'zh': "什么时间最适合您%s",
    },

    'invalid_time': {
        'en': "I didn't catch that time. Please pick from the available slots:",
        'ar': "لم أتمكّن من تحديد الوقت. يرجى الاختيار من المواعيد المتاحة:",
        'ur': "مجھے وقت سمجھ نہیں آیا۔ براہ کرم دستیاب اوقات میں سے منتخب کریں:",
        'tl': "Hindi ko nakuha ang oras na iyon. Pumili mula sa mga available na slot:",
        'es': "No pude entender esa hora. Por favor elige de los horarios disponibles:",
        'fr': "Je n'ai pas compris cette heure. Veuillez choisir parmi les créneaux disponibles :",
        'zh': "我没有听清时间。请从可用时段中选择：",
    },

    'ask_email': {
        'en': "What's your email address? We'll send you a confirmation.",
        'ar': "ما عنوان بريدك الإلكتروني؟ سنرسل لك تأكيداً بالحجز.",
        'ur': "آپ کا ای میل ایڈریس کیا ہے؟ ہم آپ کو تصدیق بھیجیں گے۔",
        'tl': "Ano ang iyong email address? Magpapadala kami ng kumpirmasyon.",
        'es': "¿Cuál es tu correo electrónico? Te enviaremos una confirmación.",
        'fr': "Quelle est votre adresse e-mail ? Nous vous enverrons une confirmation.",
        'zh': "您的电子邮箱是什么？我们会给您发送确认邮件。",
    },

    'invalid_email': {
        'en': "That doesn't look like a valid email. Please try again:",
        'ar': "يبدو أن البريد الإلكتروني غير صحيح. يرجى المحاولة مرة أخرى:",
        'ur': "یہ درست ای میل نہیں لگتا۔ براہ کرم دوبارہ کوشش کریں:",
        'tl': "Mukhang hindi valid ang email na iyon. Pakisubukan ulit:",
        'es': "Eso no parece un correo electrónico válido. Por favor intenta de nuevo:",
        'fr': "Cela ne ressemble pas à un e-mail valide. Veuillez réessayer :",
        'zh': "这似乎不是有效的电子邮箱。请重试：",
    },

    'ask_phone': {
        'en': "What's your phone number?",
        'ar': "ما رقم هاتفك؟",
        'ur': "آپ کا فون نمبر کیا ہے؟",
        'tl': "Ano ang numero ng telepono mo?",
        'es': "¿Cuál es tu número de teléfono?",
        'fr': "Quel est votre numéro de téléphone ?",
        'zh': "您的电话号码是什么？",
    },

    'invalid_phone': {
        'en': "That doesn't look like a valid phone number. Please try again:",
        'ar': "يبدو أن رقم الهاتف غير صحيح. يرجى المحاولة مرة أخرى:",
        'ur': "یہ درست فون نمبر نہیں لگتا۔ براہ کرم دوبارہ کوشش کریں:",
        'tl': "Mukhang hindi valid ang numero ng telepono. Pakisubukan ulit:",
        'es': "Eso no parece un número de teléfono válido. Por favor intenta de nuevo:",
        'fr': "Cela ne ressemble pas à un numéro de téléphone valide. Veuillez réessayer :",
        'zh': "这似乎不是有效的电话号码。请重试：",
    },

    # ── Booking confirmation ──────────────────────────────────────────────

    'booking_confirmed': {
        'en': "Your appointment is confirmed! Here are the details:",
        'ar': "تم تأكيد موعدك! إليك التفاصيل:",
        'ur': "آپ کی اپائنٹمنٹ کی تصدیق ہو گئی! یہ رہی تفصیلات:",
        'tl': "Nakumpirma na ang iyong appointment! Narito ang mga detalye:",
        'es': "¡Tu cita está confirmada! Aquí están los detalles:",
        'fr': "Votre rendez-vous est confirmé ! Voici les détails :",
        'zh': "您的预约已确认！以下是详细信息：",
    },

    'booking_date': {
        'en': "Date: {date}",
        'ar': "التاريخ: {date}",
        'ur': "تاریخ: {date}",
        'tl': "Petsa: {date}",
        'es': "Fecha: {date}",
        'fr': "Date : {date}",
        'zh': "日期：{date}",
    },

    'booking_time': {
        'en': "Time: {time}",
        'ar': "الوقت: {time}",
        'ur': "وقت: {time}",
        'tl': "Oras: {time}",
        'es': "Hora: {time}",
        'fr': "Heure : {time}",
        'zh': "时间：{time}",
    },

    'booking_doctor': {
        'en': "Doctor: Dr. {doctor}",
        'ar': "الطبيب: د. {doctor}",
        'ur': "ڈاکٹر: ڈاکٹر {doctor}",
        'tl': "Doktor: Dr. {doctor}",
        'es': "Doctor: Dr. {doctor}",
        'fr': "Médecin : Dr {doctor}",
        'zh': "医生：{doctor}医生",
    },

    'confirmation_email_sent': {
        'en': "A confirmation email has been sent to {email}.",
        'ar': "تم إرسال بريد تأكيد إلى {email}.",
        'ur': "{email} پر تصدیقی ای میل بھیج دی گئی ہے۔",
        'tl': "Naipadala na ang confirmation email sa {email}.",
        'es': "Se ha enviado un correo de confirmación a {email}.",
        'fr': "Un e-mail de confirmation a été envoyé à {email}.",
        'zh': "确认邮件已发送至 {email}。",
    },

    'previsit_form_sent': {
        'en': "We've also sent you a pre-visit form to fill out before your appointment.",
        'ar': "أرسلنا لك أيضاً نموذج ما قبل الزيارة لملئه قبل موعدك.",
        'ur': "ہم نے آپ کو اپائنٹمنٹ سے پہلے پُر کرنے کے لیے ایک پری وزٹ فارم بھی بھیجا ہے۔",
        'tl': "Nagpadala rin kami ng pre-visit form na dapat mong sagutan bago ang iyong appointment.",
        'es': "También te hemos enviado un formulario previo a la visita para que lo completes antes de tu cita.",
        'fr': "Nous vous avons également envoyé un formulaire pré-visite à remplir avant votre rendez-vous.",
        'zh': "我们还向您发送了一份就诊前表格，请在预约前填写。",
    },

    'anything_else': {
        'en': "Is there anything else I can help you with?",
        'ar': "هل هناك أي شيء آخر يمكنني مساعدتك فيه؟",
        'ur': "کیا کوئی اور چیز ہے جس میں میں آپ کی مدد کر سکتا ہوں؟",
        'tl': "May iba pa ba akong maitutulong sa iyo?",
        'es': "¿Hay algo más en lo que pueda ayudarte?",
        'fr': "Y a-t-il autre chose que je puisse faire pour vous ?",
        'zh': "还有什么我可以帮您的吗？",
    },

    # ── Waitlist ──────────────────────────────────────────────────────────

    'slot_booked': {
        'en': "This slot is fully booked. Would you like to join the waitlist%s We'll notify you immediately if a spot opens.",
        'ar': "هذا الموعد محجوز بالكامل. هل تودّ الانضمام إلى قائمة الانتظار؟ سنُعلمك فوراً عند توفّر مكان.",
        'ur': "یہ سلاٹ مکمل طور پر بک ہے۔ کیا آپ ویٹ لسٹ میں شامل ہونا چاہیں گے؟ جگہ خالی ہونے پر ہم آپ کو فوراً مطلع کریں گے۔",
        'tl': "Puno na ang slot na ito. Gusto mo bang sumali sa waitlist? Aabisuhan ka namin kaagad kapag may nagbukas na puwesto.",
        'es': "Este horario está completamente reservado. ¿Te gustaría unirte a la lista de espera? Te avisaremos de inmediato si se abre un lugar.",
        'fr': "Ce créneau est complet. Souhaitez-vous rejoindre la liste d'attente ? Nous vous préviendrons immédiatement si une place se libère.",
        'zh': "该时段已满。您想加入候补名单吗？如有空位，我们会立即通知您。",
    },

    'waitlist_joined': {
        'en': "You've been added to the waitlist at position {position}. We'll notify you as soon as a spot opens!",
        'ar': "تمت إضافتك إلى قائمة الانتظار في المركز {position}. سنُعلمك فور توفّر مكان!",
        'ur': "آپ کو ویٹ لسٹ میں پوزیشن {position} پر شامل کر لیا گیا ہے۔ جگہ خالی ہوتے ہی ہم آپ کو مطلع کریں گے!",
        'tl': "Naidagdag ka na sa waitlist sa posisyon {position}. Aabisuhan ka namin pagkakaroon ng bakante!",
        'es': "Has sido añadido a la lista de espera en la posición {position}. ¡Te avisaremos cuando haya un lugar disponible!",
        'fr': "Vous avez été ajouté à la liste d'attente en position {position}. Nous vous préviendrons dès qu'une place se libère !",
        'zh': "您已被添加到候补名单第{position}位。一有空位我们就会通知您！",
    },

    'waitlist_slot_available': {
        'en': "Great news! A spot opened with Dr. {doctor} on {date} at {time}. You have {deadline} to confirm.",
        'ar': "أخبار سارّة! تتوفّر الآن فرصة مع د. {doctor} بتاريخ {date} الساعة {time}. لديك {deadline} للتأكيد.",
        'ur': "خوشخبری! ڈاکٹر {doctor} کے پاس {date} کو {time} بجے جگہ خالی ہوئی ہے۔ تصدیق کے لیے آپ کے پاس {deadline} ہے۔",
        'tl': "Magandang balita! May bakante kay Dr. {doctor} sa {date} ng {time}. Mayroon kang {deadline} para kumpirmahin.",
        'es': "¡Buenas noticias! Se abrió un espacio con el Dr. {doctor} el {date} a las {time}. Tienes {deadline} para confirmar.",
        'fr': "Bonne nouvelle ! Une place s'est libérée avec le Dr {doctor} le {date} à {time}. Vous avez {deadline} pour confirmer.",
        'zh': "好消息！{doctor}医生在{date} {time}有一个空位。您有{deadline}时间确认。",
    },

    'waitlist_expired': {
        'en': "Your waitlist spot has expired. Would you like to join the waitlist for another slot%s",
        'ar': "انتهت صلاحية مكانك في قائمة الانتظار. هل تودّ الانضمام لقائمة انتظار موعد آخر؟",
        'ur': "آپ کی ویٹ لسٹ کی جگہ ختم ہو گئی ہے۔ کیا آپ کسی اور سلاٹ کی ویٹ لسٹ میں شامل ہونا چاہیں گے؟",
        'tl': "Nag-expire na ang iyong puwesto sa waitlist. Gusto mo bang sumali sa waitlist para sa ibang slot?",
        'es': "Tu lugar en la lista de espera ha expirado. ¿Te gustaría unirte a la lista de espera para otro horario?",
        'fr': "Votre place en liste d'attente a expiré. Souhaitez-vous rejoindre la liste d'attente pour un autre créneau ?",
        'zh': "您的候补位置已过期。您想加入另一个时段的候补名单吗？",
    },

    # ── Emergency ─────────────────────────────────────────────────────────

    'emergency_detected': {
        'en': "This sounds like an emergency. Here's what to do right now:",
        'ar': "يبدو أن هذه حالة طارئة. إليك ما يجب فعله الآن:",
        'ur': "یہ ایک ایمرجنسی لگتی ہے۔ ابھی یہ کریں:",
        'tl': "Mukhang emergency ito. Narito ang dapat mong gawin ngayon:",
        'es': "Esto parece una emergencia. Esto es lo que debes hacer ahora:",
        'fr': "Cela semble être une urgence. Voici ce qu'il faut faire maintenant :",
        'zh': "这似乎是紧急情况。您现在应该这样做：",
    },

    'emergency_slot_check': {
        'en': "Let me check our next available emergency slot...",
        'ar': "دعني أتحقّق من أقرب موعد طوارئ متاح...",
        'ur': "مجھے اگلا دستیاب ایمرجنسی سلاٹ چیک کرنے دیں...",
        'tl': "Hayaan mong tingnan ko ang susunod na available na emergency slot...",
        'es': "Déjame verificar nuestro próximo horario de emergencia disponible...",
        'fr': "Laissez-moi vérifier notre prochain créneau d'urgence disponible...",
        'zh': "让我查看我们下一个可用的紧急时段...",
    },

    'emergency_no_slots': {
        'en': "We have no emergency slots available right now. Please call us directly or go to the nearest emergency dental clinic.",
        'ar': "لا تتوفّر مواعيد طوارئ حالياً. يرجى الاتصال بنا مباشرة أو التوجّه لأقرب عيادة أسنان طوارئ.",
        'ur': "اس وقت کوئی ایمرجنسی سلاٹ دستیاب نہیں ہے۔ براہ کرم ہمیں براہ راست کال کریں یا قریب ترین ایمرجنسی ڈینٹل کلینک جائیں۔",
        'tl': "Wala kaming available na emergency slot ngayon. Tumawag sa amin nang direkta o pumunta sa pinakamalapit na emergency dental clinic.",
        'es': "No tenemos horarios de emergencia disponibles ahora. Por favor llámanos directamente o ve a la clínica dental de emergencia más cercana.",
        'fr': "Nous n'avons pas de créneaux d'urgence disponibles actuellement. Veuillez nous appeler directement ou vous rendre à la clinique dentaire d'urgence la plus proche.",
        'zh': "目前没有可用的紧急时段。请直接致电我们或前往最近的口腔急诊诊所。",
    },

    'emergency_call': {
        'en': "Prefer to call us directly?",
        'ar': "هل تفضّل الاتصال بنا مباشرة؟",
        'ur': "کیا آپ ہمیں براہ راست کال کرنا چاہیں گے؟",
        'tl': "Mas gusto mo bang tumawag sa amin nang direkta?",
        'es': "¿Prefieres llamarnos directamente?",
        'fr': "Préférez-vous nous appeler directement ?",
        'zh': "您想直接打电话给我们吗？",
    },

    # ── General ───────────────────────────────────────────────────────────

    'welcome_back': {
        'en': "Welcome back, {name}! Great to hear from you again. How can I help%s",
        'ar': "أهلاً بعودتك يا {name}! سعيدون بتواصلك مجدداً. كيف يمكنني مساعدتك؟",
        'ur': "خوش آمدید واپس، {name}! آپ سے دوبارہ بات کر کے خوشی ہوئی۔ میں کیسے مدد کر سکتا ہوں؟",
        'tl': "Maligayang pagbabalik, {name}! Natutuwa akong marinig ka ulit. Paano kita matutulungan?",
        'es': "¡Bienvenido de nuevo, {name}! Me alegra saber de ti otra vez. ¿En qué puedo ayudarte?",
        'fr': "Bon retour, {name} ! Ravi de vous revoir. Comment puis-je vous aider ?",
        'zh': "欢迎回来，{name}！很高兴再次见到您。有什么我可以帮忙的吗？",
    },

    'language_unsupported': {
        'en': "I'll respond in English as I don't support your language yet.",
        'ar': "سأجيب بالإنجليزية لأن لغتك غير مدعومة حالياً.",
        'ur': "میں انگریزی میں جواب دوں گا کیونکہ آپ کی زبان ابھی تک معاون نہیں ہے۔",
        'tl': "Sasagot ako sa Ingles dahil hindi ko pa sinusuportahan ang iyong wika.",
        'es': "Responderé en inglés ya que aún no soporto tu idioma.",
        'fr': "Je répondrai en anglais car votre langue n'est pas encore prise en charge.",
        'zh': "我将用英语回复，因为尚不支持您的语言。",
    },

    'cancel_confirm': {
        'en': "Your appointment has been cancelled successfully.",
        'ar': "تم إلغاء موعدك بنجاح.",
        'ur': "آپ کی اپائنٹمنٹ کامیابی سے منسوخ ہو گئی ہے۔",
        'tl': "Matagumpay na nakansela ang iyong appointment.",
        'es': "Tu cita ha sido cancelada exitosamente.",
        'fr': "Votre rendez-vous a été annulé avec succès.",
        'zh': "您的预约已成功取消。",
    },

    'error_generic': {
        'en': "Sorry, something went wrong. Please try again.",
        'ar': "عذراً، حدث خطأ ما. يرجى المحاولة مرة أخرى.",
        'ur': "معذرت، کچھ غلط ہو گیا۔ براہ کرم دوبارہ کوشش کریں۔",
        'tl': "Paumanhin, may nangyaring mali. Pakisubukan ulit.",
        'es': "Lo siento, algo salió mal. Por favor intenta de nuevo.",
        'fr': "Désolé, quelque chose s'est mal passé. Veuillez réessayer.",
        'zh': "抱歉，出了点问题。请重试。",
    },

    'goodbye': {
        'en': "Thank you for visiting! Have a wonderful day.",
        'ar': "شكراً لزيارتك! أتمنى لك يوماً سعيداً.",
        'ur': "آنے کا شکریہ! آپ کا دن اچھا گزرے۔",
        'tl': "Salamat sa pagbisita! Magandang araw sa iyo.",
        'es': "¡Gracias por visitarnos! Que tengas un maravilloso día.",
        'fr': "Merci de votre visite ! Passez une merveilleuse journée.",
        'zh': "感谢您的来访！祝您有美好的一天。",
    },

    'handoff_connecting': {
        'en': "Let me connect you with one of our team members who can help you better.",
        'ar': "دعني أوصلك بأحد أعضاء فريقنا ليساعدك بشكل أفضل.",
        'ur': "مجھے آپ کو ہماری ٹیم کے ایک رکن سے جوڑنے دیں جو آپ کی بہتر مدد کر سکتا ہے۔",
        'tl': "Ikokonekta kita sa isa sa aming team na mas makakatulong sa iyo.",
        'es': "Déjame conectarte con uno de nuestros miembros del equipo que puede ayudarte mejor.",
        'fr': "Laissez-moi vous mettre en contact avec un membre de notre équipe qui pourra mieux vous aider.",
        'zh': "让我为您转接我们的一位团队成员，他们可以更好地帮助您。",
    },

    'handoff_connected': {
        'en': "You are now connected with {staff} from our team.",
        'ar': "أنت الآن متصل بـ {staff} من فريقنا.",
        'ur': "آپ اب ہماری ٹیم سے {staff} کے ساتھ جڑے ہوئے ہیں۔",
        'tl': "Nakakonekta ka na kay {staff} mula sa aming team.",
        'es': "Ahora estás conectado con {staff} de nuestro equipo.",
        'fr': "Vous êtes maintenant en contact avec {staff} de notre équipe.",
        'zh': "您现在已与我们团队的{staff}连接。",
    },

    'handoff_busy': {
        'en': "Our team is currently busy. We will message you back within 1 hour.",
        'ar': "فريقنا مشغول حالياً. سنراسلك خلال ساعة واحدة.",
        'ur': "ہماری ٹیم اس وقت مصروف ہے۔ ہم ایک گھنٹے کے اندر آپ کو پیغام بھیجیں گے۔",
        'tl': "Abala ang aming team sa ngayon. Magme-message kami sa iyo sa loob ng 1 oras.",
        'es': "Nuestro equipo está ocupado en este momento. Te responderemos dentro de 1 hora.",
        'fr': "Notre équipe est actuellement occupée. Nous vous répondrons dans l'heure.",
        'zh': "我们的团队目前很忙。我们将在1小时内回复您。",
    },

    'loyalty_balance': {
        'en': "You currently have {points} loyalty points worth {value} {currency}.",
        'ar': "لديك حالياً {points} نقطة ولاء بقيمة {value} {currency}.",
        'ur': "آپ کے پاس اس وقت {points} لائلٹی پوائنٹس ہیں جن کی مالیت {value} {currency} ہے۔",
        'tl': "Mayroon kang {points} loyalty points na nagkakahalaga ng {value} {currency}.",
        'es': "Actualmente tienes {points} puntos de lealtad con un valor de {value} {currency}.",
        'fr': "Vous avez actuellement {points} points de fidélité d'une valeur de {value} {currency}.",
        'zh': "您目前有{points}忠诚积分，价值{value} {currency}。",
    },

    'discount_applied': {
        'en': "Code applied! Your total is {new_total} {currency} instead of {original} {currency} ({percent}% off).",
        'ar': "تم تطبيق الكود! إجمالي المبلغ {new_total} {currency} بدلاً من {original} {currency} (خصم {percent}%).",
        'ur': "کوڈ لاگو ہو گیا! آپ کی کل رقم {original} {currency} کے بجائے {new_total} {currency} ہے ({percent}% چھوٹ)۔",
        'tl': "Na-apply na ang code! Ang total mo ay {new_total} {currency} sa halip na {original} {currency} ({percent}% off).",
        'es': "¡Código aplicado! Tu total es {new_total} {currency} en vez de {original} {currency} ({percent}% de descuento).",
        'fr': "Code appliqué ! Votre total est de {new_total} {currency} au lieu de {original} {currency} ({percent}% de réduction).",
        'zh': "优惠码已应用！您的总价为{new_total} {currency}，原价{original} {currency}（{percent}%折扣）。",
    },

    'discount_invalid': {
        'en': "This code is not valid. Please check and try again.",
        'ar': "هذا الكود غير صالح. يرجى التحقق والمحاولة مرة أخرى.",
        'ur': "یہ کوڈ درست نہیں ہے۔ براہ کرم چیک کریں اور دوبارہ کوشش کریں۔",
        'tl': "Hindi valid ang code na ito. Pakitingnan at subukan ulit.",
        'es': "Este código no es válido. Por favor verifica e intenta de nuevo.",
        'fr': "Ce code n'est pas valide. Veuillez vérifier et réessayer.",
        'zh': "此优惠码无效。请检查后重试。",
    },

    'discount_expired': {
        'en': "This code expired on {date}.",
        'ar': "انتهت صلاحية هذا الكود بتاريخ {date}.",
        'ur': "اس کوڈ کی میعاد {date} کو ختم ہو گئی۔",
        'tl': "Nag-expire ang code na ito noong {date}.",
        'es': "Este código expiró el {date}.",
        'fr': "Ce code a expiré le {date}.",
        'zh': "此优惠码已于{date}过期。",
    },

    # ── Pre-visit form labels ─────────────────────────────────────────────

    'form_title': {
        'en': "Pre-Visit Medical Form",
        'ar': "نموذج المعلومات الطبية قبل الزيارة",
        'ur': "پری وزٹ میڈیکل فارم",
        'tl': "Pre-Visit Medical Form",
        'es': "Formulario Médico Pre-Visita",
        'fr': "Formulaire Médical Pré-Visite",
        'zh': "就诊前医疗表格",
    },

    'form_personal': {
        'en': "Personal Information",
        'ar': "المعلومات الشخصية",
        'ur': "ذاتی معلومات",
        'tl': "Personal na Impormasyon",
        'es': "Información Personal",
        'fr': "Informations Personnelles",
        'zh': "个人信息",
    },

    'form_name': {
        'en': "Full Name",
        'ar': "الاسم الكامل",
        'ur': "پورا نام",
        'tl': "Buong Pangalan",
        'es': "Nombre Completo",
        'fr': "Nom Complet",
        'zh': "全名",
    },

    'form_dob': {
        'en': "Date of Birth",
        'ar': "تاريخ الميلاد",
        'ur': "تاریخ پیدائش",
        'tl': "Petsa ng Kapanganakan",
        'es': "Fecha de Nacimiento",
        'fr': "Date de Naissance",
        'zh': "出生日期",
    },

    'form_gender': {
        'en': "Gender",
        'ar': "الجنس",
        'ur': "جنس",
        'tl': "Kasarian",
        'es': "Género",
        'fr': "Genre",
        'zh': "性别",
    },

    'form_male': {
        'en': "Male",
        'ar': "ذكر",
        'ur': "مرد",
        'tl': "Lalaki",
        'es': "Masculino",
        'fr': "Masculin",
        'zh': "男",
    },

    'form_female': {
        'en': "Female",
        'ar': "أنثى",
        'ur': "عورت",
        'tl': "Babae",
        'es': "Femenino",
        'fr': "Féminin",
        'zh': "女",
    },

    'form_other': {
        'en': "Other",
        'ar': "آخر",
        'ur': "دیگر",
        'tl': "Iba pa",
        'es': "Otro",
        'fr': "Autre",
        'zh': "其他",
    },

    'form_medical_history': {
        'en': "Medical History",
        'ar': "التاريخ الطبي",
        'ur': "طبی تاریخ",
        'tl': "Kasaysayang Medikal",
        'es': "Historial Médico",
        'fr': "Antécédents Médicaux",
        'zh': "病史",
    },

    'form_diabetes': {
        'en': "Diabetes",
        'ar': "السكري",
        'ur': "ذیابیطس",
        'tl': "Diabetes",
        'es': "Diabetes",
        'fr': "Diabète",
        'zh': "糖尿病",
    },

    'form_hypertension': {
        'en': "Hypertension",
        'ar': "ارتفاع ضغط الدم",
        'ur': "ہائی بلڈ پریشر",
        'tl': "Hypertension",
        'es': "Hipertensión",
        'fr': "Hypertension",
        'zh': "高血压",
    },

    'form_heart_disease': {
        'en': "Heart Disease",
        'ar': "أمراض القلب",
        'ur': "دل کی بیماری",
        'tl': "Sakit sa Puso",
        'es': "Enfermedad Cardíaca",
        'fr': "Maladie Cardiaque",
        'zh': "心脏病",
    },

    'form_blood_thinners': {
        'en': "Blood Thinners",
        'ar': "أدوية سيولة الدم",
        'ur': "خون پتلا کرنے والی ادویات",
        'tl': "Blood Thinners",
        'es': "Anticoagulantes",
        'fr': "Anticoagulants",
        'zh': "血液稀释剂",
    },

    'form_allergies_check': {
        'en': "Allergies",
        'ar': "حساسية",
        'ur': "الرجی",
        'tl': "Mga Allergy",
        'es': "Alergias",
        'fr': "Allergies",
        'zh': "过敏",
    },

    'form_pregnancy': {
        'en': "Pregnancy",
        'ar': "حمل",
        'ur': "حمل",
        'tl': "Pagbubuntis",
        'es': "Embarazo",
        'fr': "Grossesse",
        'zh': "怀孕",
    },

    'form_asthma': {
        'en': "Asthma",
        'ar': "الربو",
        'ur': "دمہ",
        'tl': "Hika",
        'es': "Asma",
        'fr': "Asthme",
        'zh': "哮喘",
    },

    'form_other_condition': {
        'en': "Other (please specify)",
        'ar': "أخرى (يرجى التحديد)",
        'ur': "دیگر (براہ کرم وضاحت کریں)",
        'tl': "Iba pa (pakitukoy)",
        'es': "Otro (por favor especifique)",
        'fr': "Autre (veuillez préciser)",
        'zh': "其他（请注明）",
    },

    'form_medications': {
        'en': "Current Medications",
        'ar': "الأدوية الحالية",
        'ur': "موجودہ ادویات",
        'tl': "Kasalukuyang Gamot",
        'es': "Medicamentos Actuales",
        'fr': "Médicaments Actuels",
        'zh': "目前用药",
    },

    'form_allergies': {
        'en': "Known Allergies",
        'ar': "أنواع الحساسية المعروفة",
        'ur': "معلوم الرجیاں",
        'tl': "Mga Kilalang Allergy",
        'es': "Alergias Conocidas",
        'fr': "Allergies Connues",
        'zh': "已知过敏",
    },

    'form_insurance': {
        'en': "Insurance (Optional)",
        'ar': "التأمين (اختياري)",
        'ur': "انشورنس (اختیاری)",
        'tl': "Insurance (Opsyonal)",
        'es': "Seguro (Opcional)",
        'fr': "Assurance (Facultatif)",
        'zh': "保险（可选）",
    },

    'form_insurance_provider': {
        'en': "Insurance Provider",
        'ar': "شركة التأمين",
        'ur': "انشورنس فراہم کنندہ",
        'tl': "Insurance Provider",
        'es': "Proveedor de Seguros",
        'fr': "Assureur",
        'zh': "保险提供商",
    },

    'form_policy_number': {
        'en': "Policy Number",
        'ar': "رقم الوثيقة",
        'ur': "پالیسی نمبر",
        'tl': "Policy Number",
        'es': "Número de Póliza",
        'fr': "Numéro de Police",
        'zh': "保单号码",
    },

    'form_signature': {
        'en': "Digital Signature",
        'ar': "التوقيع الرقمي",
        'ur': "ڈیجیٹل دستخط",
        'tl': "Digital na Pirma",
        'es': "Firma Digital",
        'fr': "Signature Numérique",
        'zh': "电子签名",
    },

    'form_signature_note': {
        'en': "By signing, you confirm the information above is accurate.",
        'ar': "بتوقيعك، تؤكّد أن المعلومات أعلاه صحيحة.",
        'ur': "دستخط کر کے، آپ تصدیق کرتے ہیں کہ اوپر دی گئی معلومات درست ہیں۔",
        'tl': "Sa pamamagitan ng pagpirma, kinukumpirma mo na tama ang impormasyon sa itaas.",
        'es': "Al firmar, confirmas que la información anterior es precisa.",
        'fr': "En signant, vous confirmez que les informations ci-dessus sont exactes.",
        'zh': "签名即表示您确认以上信息准确无误。",
    },

    'form_clear': {
        'en': "Clear Signature",
        'ar': "مسح التوقيع",
        'ur': "دستخط صاف کریں",
        'tl': "Burahin ang Pirma",
        'es': "Borrar Firma",
        'fr': "Effacer la Signature",
        'zh': "清除签名",
    },

    'form_submit': {
        'en': "Submit Form",
        'ar': "إرسال النموذج",
        'ur': "فارم جمع کرائیں",
        'tl': "Isumite ang Form",
        'es': "Enviar Formulario",
        'fr': "Soumettre le Formulaire",
        'zh': "提交表格",
    },

    'form_submitted': {
        'en': "Form already submitted. Thank you!",
        'ar': "تم إرسال النموذج مسبقاً. شكراً لك!",
        'ur': "فارم پہلے ہی جمع ہو چکا ہے۔ شکریہ!",
        'tl': "Naisumite na ang form. Salamat!",
        'es': "El formulario ya fue enviado. ¡Gracias!",
        'fr': "Formulaire déjà soumis. Merci !",
        'zh': "表格已提交。谢谢！",
    },

    'form_invalid': {
        'en': "This link is invalid or has expired.",
        'ar': "هذا الرابط غير صالح أو منتهي الصلاحية.",
        'ur': "یہ لنک غیر درست ہے یا اس کی میعاد ختم ہو چکی ہے۔",
        'tl': "Hindi valid o nag-expire na ang link na ito.",
        'es': "Este enlace no es válido o ha expirado.",
        'fr': "Ce lien est invalide ou a expiré.",
        'zh': "此链接无效或已过期。",
    },

    'form_success': {
        'en': "Thank you! Your pre-visit form has been submitted successfully.",
        'ar': "شكراً لك! تم إرسال نموذج ما قبل الزيارة بنجاح.",
        'ur': "شکریہ! آپ کا پری وزٹ فارم کامیابی سے جمع ہو گیا ہے۔",
        'tl': "Salamat! Matagumpay na naisumite ang iyong pre-visit form.",
        'es': "¡Gracias! Tu formulario pre-visita ha sido enviado exitosamente.",
        'fr': "Merci ! Votre formulaire pré-visite a été soumis avec succès.",
        'zh': "谢谢！您的就诊前表格已成功提交。",
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def t(key, lang='en', **kwargs):
    """Get translated message. Falls back to English if translation missing.
    Usage: t('greeting', 'ar')
           t('nice_to_meet', 'ar', name='Ahmed')
    """
    translations = TRANSLATIONS.get(key, {})
    text = translations.get(lang) or translations.get('en', f'[{key}]')
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def get_rtl_direction(lang):
    """Return 'rtl' for Arabic/Urdu, 'ltr' for others."""
    return 'rtl' if lang in ('ar', 'ur') else 'ltr'
