"""Language selection.

The rule that shapes this module: **only what is displayed is translated.**

Every chip carries a `label` and a `value`. The label is what the buyer reads;
the value is what the server receives, what the extractor matches and what ends
up in the group's specification. Translating the label and never the value is
what keeps a Hindi-speaking buyer and an English-speaking buyer asking for the
same 18 mm BWR plywood in the *same* buying group -- which is the entire point
of the product. A translated value would silently split the pool in two and
nobody would ever notice.

So the dictionary is keyed by the English source string, translation happens at
the rendering boundary, and anything with no entry falls through to English
rather than failing. Proper nouns (Century, Fevicol) and trade codes (MR, BWR,
ISI) are deliberately left alone -- that is how they are said in Hindi too.
"""
from __future__ import annotations

import re
from typing import Any

DEFAULT = "en"

#: Offered on the opening screen. `chip` is what the buyer taps.
LANGUAGES: tuple[dict[str, str], ...] = (
    {"code": "en", "label": "English", "chip": "English"},
    {"code": "hi", "label": "हिंदी", "chip": "हिंदी"},
)

LANGUAGE_CODES = tuple(l["code"] for l in LANGUAGES)

#: Asked before anything else, so it has to read in both languages at once.
LANGUAGE_QUESTION = "Which language would you like to continue in?\nकिस भाषा में बात करें?"


def language_of(text: str) -> str | None:
    """Read a language choice, tapped or typed."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    if raw in ("hi", "hindi") or re.search(r"हिंदी|हिन्दी|hindi|hindee", raw, re.I):
        return "hi"
    if raw in ("en", "english") or re.search(r"english|angrezi|अंग्रे", raw, re.I):
        return "en"
    return None


# --------------------------------------------------------------------------- #
# Hindi
# --------------------------------------------------------------------------- #
HINDI: dict[str, str] = {
    # -- language + greeting ------------------------------------------------ #
    "English": "English",
    "हिंदी": "हिंदी",

    # -- the shared flow ---------------------------------------------------- #
    "What's your mobile number?\n\nWe'll use it to check if you already have a "
    "request with us, and to message you when your group price improves.":
        "आपका मोबाइल नंबर क्या है?\n\nइससे हम देख लेंगे कि आपकी कोई पुरानी रिक्वेस्ट "
        "है या नहीं, और ग्रुप की कीमत घटते ही आपको मैसेज कर देंगे।",
    "Almost there 👍 What's your mobile number?\n\nWe'll use it to check if you "
    "already have a request with us, and to message you when your group price "
    "improves.":
        "बस थोड़ा और 👍 आपका मोबाइल नंबर क्या है?\n\nइससे हम देख लेंगे कि आपकी कोई "
        "पुरानी रिक्वेस्ट है या नहीं, और ग्रुप की कीमत घटते ही आपको मैसेज कर देंगे।",
    "10-digit mobile number": "10 अंकों का मोबाइल नंबर",
    "Hello 👋\n\nWhat are you looking for?": "नमस्ते 👋\n\nआपको क्या चाहिए?",
    "What's your address?": "आपका पता क्या है?",
    "Where should we deliver your order?": "आपका ऑर्डर कहाँ डिलीवर करें?",
    "e.g. Satellite, Ahmedabad": "जैसे सैटेलाइट, अहमदाबाद",
    "Which city is that in?": "यह किस शहर में है?",
    "Just the area and city is enough 🙂 Where should we deliver?":
        "बस इलाका और शहर बता दीजिए 🙂 डिलीवरी कहाँ करनी है?",
    "Which city are you in?": "आप किस शहर में हैं?",
    "e.g. Ahmedabad": "जैसे अहमदाबाद",
    "Which area within the city?": "शहर में कौन-से इलाके में?",
    "e.g. Satellite": "जैसे सैटेलाइट",
    "Adhesive (Fevicol)": "अडहेसिव (फ़ेविकोल)",
    "Or just type it, e.g. “100 sheets plywood”":
        "या लिख दीजिए, जैसे “100 शीट प्लाईवुड”",
    "Or just type it, e.g. “5 kg nails”": "या लिख दीजिए, जैसे “5 किलो कील”",
    "Anything else I can help you pool up?": "और कुछ जिसमें मैं मदद कर सकूँ?",
    "You already have an open request for **{existing} · {product}**.\n\n"
    "Shall I add this {adding} to it, or keep it as a separate request?":
        "आपकी पहले से एक खुली रिक्वेस्ट है — **{existing} · {product}**।\n\n"
        "क्या इन {adding} को उसी में जोड़ दूँ, या अलग रिक्वेस्ट रखूँ?",
    # -- the one card a buyer gets after placing a request ------------------ #
    "You're the first buyer in this group 🚀": "आप इस ग्रुप के पहले खरीदार हैं 🚀",
    "Your requirement is pooled with other buyers 🎉":
        "आपकी ज़रूरत दूसरे खरीदारों के साथ जुड़ गई है 🎉",
    "Group price now": "अभी ग्रुप की कीमत",
    "per {unit}": "प्रति {unit}",
    "Price": "कीमत",
    "Being negotiated": "बातचीत चल रही है",
    "Next price level": "अगली कीमत",
    "{gap} more to get there": "{gap} और चाहिए",
    "See your order": "अपना ऑर्डर देखें",
    "Share with others": "दूसरों के साथ साझा करें",
    "yours": "आपके",
    "Saving": "बचत",
    "in total": "कुल मिलाकर",
    "pooled": "कुल",

    "➕ Add to that request": "➕ उसी में जोड़ दें",
    "📄 Keep it separate": "📄 अलग रखें",
    "Done 👍 Added to your existing request — it is now **{total}**, in one "
    "order rather than two.":
        "हो गया 👍 आपकी पुरानी रिक्वेस्ट में जोड़ दिया — अब यह **{total}** है, "
        "दो की जगह एक ही ऑर्डर में।",
    "No problem — I'll keep them separate. 👍":
        "कोई बात नहीं — मैं इन्हें अलग रखूँगा। 👍",
    "Want to set up something new?": "कुछ नया शुरू करें?",
    "What would you like to buy instead?": "इसकी जगह क्या खरीदना चाहेंगे?",
    "When are you planning to purchase?": "आप कब तक खरीदना चाहते हैं?",
    "If waiting another 5-7 days could give you a better group price, would you "
    "be comfortable waiting?":
        "अगर 5-7 दिन और रुकने से ग्रुप को बेहतर कीमत मिल सके, तो क्या आप रुक पाएँगे?",
    "Great. I'll combine your requirement with buyers looking for similar "
    "products in your area.\n\nWhat's your name?":
        "बढ़िया। मैं आपकी ज़रूरत को आपके इलाके के दूसरे खरीदारों के साथ जोड़ दूँगा।"
        "\n\nआपका नाम क्या है?",
    "Your name": "आपका नाम",
    "What are you looking to buy?": "आप क्या खरीदना चाहते हैं?",
    "Type a message": "मैसेज लिखें",
    "Type your message…": "अपना मैसेज लिखें…",
    "Ask me anything…": "कुछ भी पूछिए…",
    "Quantity in {unit}": "मात्रा ({unit})",

    # -- timing / waiting chips --------------------------------------------- #
    "Immediately": "तुरंत",
    "Within 3 days": "3 दिन में",
    "Within 7 days": "7 दिन में",
    "Within 15 days": "15 दिन में",
    "Within 30 days": "30 दिन में",
    "Choose a date": "तारीख़ चुनें",
    "Sure — pick your planned purchase date:": "ठीक है — खरीदने की तारीख़ चुनिए:",
    "Yes, I can wait": "हाँ, रुक सकता हूँ",
    "Maybe": "शायद",
    "No, I need it by then": "नहीं, तब तक चाहिए",

    # -- generic answers ---------------------------------------------------- #
    "Yes": "हाँ",
    "No": "नहीं",
    "Skip": "छोड़ें",
    "Not Sure": "पता नहीं",
    "No Preference": "कोई फ़र्क़ नहीं",
    "Mixed": "मिला-जुला",
    "Other": "अन्य",
    "{brand} Only": "सिर्फ़ {brand}",

    # -- plywood ------------------------------------------------------------ #
    "Plywood": "प्लाईवुड",
    "plywood": "प्लाईवुड",
    "How many sheets do you need?": "आपको कितनी शीट चाहिए?",
    "Which grade of plywood?\n\nMR is for dry interiors, BWR resists moisture, "
    "BWP/Marine survives water.":
        "प्लाईवुड की कौन-सी ग्रेड चाहिए?\n\nMR सूखी जगहों के लिए, BWR नमी सह लेता है, "
        "BWP/Marine पानी में भी टिकता है।",
    "Fire Retardant": "फ़ायर रिटार्डेंट",
    "What thickness?": "कितनी मोटाई?",
    "Which sheet size?": "शीट का साइज़ कौन-सा?",
    "Any preference on the core timber?": "अंदर की लकड़ी (कोर) की कोई पसंद?",
    "Hardwood": "हार्डवुड",
    "Gurjan": "गुर्जन",
    "Poplar": "पॉपलर",
    "Eucalyptus": "यूकेलिप्टस",
    "What surface finish?": "ऊपर की फ़िनिश कैसी चाहिए?",
    "Plain / unfinished": "सादा / बिना फ़िनिश",
    "One side teak": "एक तरफ़ टीक",
    "Both sides teak": "दोनों तरफ़ टीक",
    "Laminated": "लैमिनेटेड",
    "Any preferred brand?": "कोई पसंदीदा ब्रांड?",
    "If another reliable brand gives the group a significantly better price, "
    "would you consider it?":
        "अगर कोई दूसरा भरोसेमंद ब्रांड ग्रुप को काफ़ी बेहतर कीमत दे, तो क्या आप उसे लेंगे?",
    "What is it for?": "यह किस काम के लिए है?",
    "Furniture": "फ़र्नीचर",
    "Interior / fit-out": "इंटीरियर / फ़िट-आउट",
    "Kitchen": "किचन",
    "Shuttering / construction": "शटरिंग / निर्माण",
    "Packaging": "पैकेजिंग",
    "Do you need ISI-marked (BIS certified) sheets?":
        "क्या आपको ISI मार्क (BIS सर्टिफ़ाइड) शीट चाहिए?",
    "Yes, ISI marked": "हाँ, ISI मार्क",
    "Not required": "ज़रूरत नहीं",
    "Do you have a budget per sheet in mind? (optional)":
        "प्रति शीट कोई बजट सोचा है? (ज़रूरी नहीं)",
    "Under ₹1,000": "₹1,000 से कम",
    "Above ₹2,000": "₹2,000 से ऊपर",
    "Plywood is bought by the sheet and discounts hard by volume — pooling a "
    "few orders moves the price meaningfully.":
        "प्लाईवुड शीट के हिसाब से बिकता है और मात्रा बढ़ने पर कीमत तेज़ी से गिरती है — "
        "कुछ ऑर्डर मिला देने से फ़र्क़ साफ़ दिखता है।",

    # -- companion products: the offer -------------------------------------- #
    "One last thing 👇\n\nMost plywood buyers need a few of these in the same "
    "order. Adding them costs nothing now — we'll ask the supplier to quote "
    "them with the board, so the group gets a better rate on those too.":
        "आख़िरी बात 👇\n\nप्लाईवुड लेने वाले ज़्यादातर लोगों को इनमें से कुछ चीज़ें उसी "
        "ऑर्डर में चाहिए होती हैं। अभी जोड़ने का कोई पैसा नहीं लगता — हम सप्लायर से "
        "बोर्ड के साथ इनका भी रेट पूछेंगे, ताकि ग्रुप को इन पर भी बेहतर कीमत मिले।",
    "No thanks": "नहीं, धन्यवाद",
    "For the {product} — same name, number and delivery address as your "
    "{main} order?":
        "{product} के लिए — नाम, नंबर और डिलीवरी पता वही रहेगा जो आपके {main} "
        "ऑर्डर में है?",
    "✅ Yes, same details": "✅ हाँ, वही",
    "✏️ No, different": "✏️ नहीं, अलग",
    "✅ That's everything": "✅ बस इतना ही",
    "Anything else you need with it? We'll ask the supplier to quote these "
    "alongside your order.":
        "इसके साथ और कुछ चाहिए? हम सप्लायर से आपके ऑर्डर के साथ इनका भी रेट पूछ लेंगे।",

    "Adhesive": "अडहेसिव (गोंद)",
    "Fevicol, white glue, synthetic resin": "फ़ेविकोल, सफ़ेद गोंद, सिंथेटिक रेज़िन",
    "Nails & pins": "कील और पिन",
    "Wire nails, panel pins, brad nails": "वायर कील, पैनल पिन, ब्रैड कील",
    "Screws": "स्क्रू (पेच)",
    "Wood screws, self-tapping screws": "लकड़ी के स्क्रू, सेल्फ़-टैपिंग स्क्रू",
    "Hinges & fittings": "कब्ज़े और फ़िटिंग",
    "Hinges, channels, handles, locks": "कब्ज़े, चैनल, हैंडल, ताले",
    "Laminate / sunmica": "लैमिनेट / सनमाइका",
    "Decorative laminate sheets": "डेकोरेटिव लैमिनेट शीट",
    "Edge banding tape": "एज बैंडिंग टेप",
    "PVC edge banding / beading": "PVC एज बैंडिंग / बीडिंग",

    # -- companion products: their own questions ---------------------------- #
    "Let's pin down the adhesive 🧴": "अब गोंद की बात 🧴",
    "How much adhesive do you need, in kg?": "कितना गोंद चाहिए, किलो में?",
    "Which adhesive?\n\nWhite glue is the everyday carpentry one, synthetic "
    "resin holds under load, rubber-based is for laminate and sunmica.":
        "कौन-सा गोंद?\n\nसफ़ेद गोंद रोज़ के काम का है, सिंथेटिक रेज़िन वज़न सहता है, "
        "रबर वाला लैमिनेट और सनमाइका के लिए है।",
    "White glue": "सफ़ेद गोंद",
    "Synthetic resin": "सिंथेटिक रेज़िन",
    "Rubber-based": "रबर वाला",
    "Epoxy": "एपॉक्सी",
    "Which pack size suits you? Bigger packs price better per kg.":
        "कौन-सा पैक ठीक रहेगा? बड़े पैक में प्रति किलो रेट कम पड़ता है।",
    "Any brand you usually buy?": "कोई ब्रांड जो आप आमतौर पर लेते हैं?",

    "Now the nails 📌": "अब कील की बात 📌",
    "How many kg of nails?": "कितने किलो कील चाहिए?",
    "What size nails?\n\nLength in inches — it's the first thing a supplier asks.":
        "कील का साइज़ क्या?\n\nलंबाई इंच में — सप्लायर सबसे पहले यही पूछता है।",
    "Which type?\n\nWire nails are the common ones, panel pins are thin and "
    "headless for beading, brads go in a nail gun.":
        "कौन-सी किस्म?\n\nवायर कील आम हैं, पैनल पिन पतली और बिना सिर वाली होती हैं "
        "(बीडिंग के लिए), ब्रैड कील गन में लगती हैं।",
    "Wire": "वायर",
    "Panel pin": "पैनल पिन",
    "Brad": "ब्रैड",
    "Concrete": "कंक्रीट",
    "U-nail": "यू-कील",
    "Plain steel is fine for indoor work — or do you need galvanised?":
        "अंदर के काम के लिए सादा स्टील चलेगा — या गैल्वनाइज़्ड चाहिए?",
    "Plain / MS": "सादा / MS",
    "Galvanised": "गैल्वनाइज़्ड",
    "Stainless": "स्टेनलेस",

    "And the screws 🔩": "अब स्क्रू की बात 🔩",
    "How many boxes of screws? (a box is usually 100 or 200 pieces)":
        "कितने डिब्बे स्क्रू चाहिए? (एक डिब्बे में आमतौर पर 100 या 200 पीस)",
    "What size screws? Gauge × length is how they're sold.":
        "स्क्रू का साइज़ क्या? ये गेज × लंबाई के हिसाब से बिकते हैं।",
    "Which type?": "कौन-सी किस्म?",
    "Wood": "लकड़ी वाले",
    "Self-tapping": "सेल्फ़-टैपिंग",
    "Drywall": "ड्राईवॉल",

    "Let's get the fittings right 🚪": "अब फ़िटिंग की बात 🚪",
    "How many pieces?": "कितने पीस चाहिए?",
    "Which material?": "कौन-सी धातु?",
    "Stainless steel": "स्टेनलेस स्टील",
    "Mild steel": "माइल्ड स्टील (लोहा)",
    "Brass": "पीतल",
    "Powder coated": "पाउडर कोटेड",
    "Which fitting do you need most of?": "सबसे ज़्यादा कौन-सी फ़िटिंग चाहिए?",
    "Butt hinge": "साधारण कब्ज़ा",
    "Soft-close hinge": "सॉफ़्ट-क्लोज़ कब्ज़ा",
    "Telescopic channel": "टेलिस्कोपिक चैनल",
    "Drawer slide": "ड्रॉअर स्लाइड",
    "Handle": "हैंडल",
    "Lock": "ताला",

    "Now the laminate 🎨": "अब लैमिनेट की बात 🎨",
    "How many laminate sheets?": "कितनी लैमिनेट शीट चाहिए?",
    "What thickness?\n\n0.8 mm is the usual interior sheet, 1 mm and above for "
    "high-wear surfaces.":
        "कितनी मोटाई?\n\n0.8 मिमी आम तौर पर अंदर के काम के लिए, 1 मिमी और उससे ऊपर "
        "ज़्यादा घिसने वाली सतहों के लिए।",
    "Which finish?": "कौन-सी फ़िनिश?",
    "Glossy": "चमकदार",
    "Matte": "मैट",
    "Textured": "टेक्सचर्ड",
    "Suede": "स्वेड",
    "Any brand in mind?": "कोई ब्रांड सोचा है?",

    "Last one — the edge banding 🎗️": "आख़िरी — एज बैंडिंग 🎗️",
    "How many rolls? (a roll is usually 50 metres)":
        "कितने रोल चाहिए? (एक रोल आमतौर पर 50 मीटर)",
    "What width? It should match the board edge — 19 mm and 22 mm are standard.":
        "कितनी चौड़ाई? यह बोर्ड के किनारे से मेल खानी चाहिए — 19 मिमी और 22 मिमी आम हैं।",
    "Wood veneer": "लकड़ी का विनियर",

    # -- clarifiers and escapes --------------------------------------------- #
    "No worries — just the number is fine. How many do you need?":
        "कोई बात नहीं — सिर्फ़ संख्या बता दीजिए। कितने चाहिए?",
    "Almost there 🙂 Which city should I look for other buyers in?":
        "बस हो ही गया 🙂 किस शहर में दूसरे खरीदार ढूँढूँ?",
    "What name should I save this under?": "किस नाम से सेव करूँ?",
    "Let's try that again — a 10-digit number, digits only. It's only used to "
    "send you price updates and to find your requests later.":
        "एक बार फिर कोशिश करें — 10 अंकों का नंबर, सिर्फ़ अंक। यह सिर्फ़ कीमत की जानकारी "
        "भेजने और आपकी रिक्वेस्ट ढूँढने के काम आता है।",
    "No problem — pick one of these, or just tell me what you need:":
        "कोई बात नहीं — इनमें से कोई चुनिए, या बता दीजिए कि क्या चाहिए:",
    "🔁 Change product": "🔁 प्रोडक्ट बदलें",
    "📋 My requests": "📋 मेरी रिक्वेस्ट",
    "✖ Cancel": "✖ रद्द करें",
    "➕ New request": "➕ नई रिक्वेस्ट",
    "➕ Add a new request": "➕ नई रिक्वेस्ट जोड़ें",
    "📋 Show my past requests": "📋 पुरानी रिक्वेस्ट दिखाएँ",
    "📋 Open my requests": "📋 मेरी रिक्वेस्ट खोलें",
    "📲 Share on WhatsApp": "📲 व्हाट्सऐप पर भेजें",
    "🛒 I'm ready to buy": "🛒 मैं खरीदने को तैयार हूँ",
    "➕ Another product": "➕ कोई और प्रोडक्ट",
    "✖ Cancel request": "✖ रिक्वेस्ट रद्द करें",
    "Keep them all": "सभी रहने दें",
    "Sure — which one should I cancel?": "ठीक है — कौन-सी रद्द करूँ?",
    "Kept them all 👍 Nothing was cancelled.": "सभी रहने दीं 👍 कुछ भी रद्द नहीं हुआ।",

    # -- city names --------------------------------------------------------- #
    # Shown in Hindi, stored in English. The extractor canonicalises whichever
    # script the buyer typed, so both spellings pool into one city's group.
    "Ahmedabad": "अहमदाबाद",
    "Surat": "सूरत",
    "Vadodara": "वडोदरा",
    "Rajkot": "राजकोट",
    "Gandhinagar": "गांधीनगर",
    "Mumbai": "मुंबई",
    "Pune": "पुणे",
    "Nashik": "नासिक",
    "Nagpur": "नागपुर",
    "Delhi": "दिल्ली",
    "Gurugram": "गुरुग्राम",
    "Noida": "नोएडा",
    "Jaipur": "जयपुर",
    "Lucknow": "लखनऊ",
    "Indore": "इंदौर",
    "Bhopal": "भोपाल",
    "Bengaluru": "बेंगलुरु",
    "Hyderabad": "हैदराबाद",
    "Chennai": "चेन्नई",
    "Coimbatore": "कोयंबटूर",
    "Kochi": "कोच्चि",
    "Kolkata": "कोलकाता",
    "Chandigarh": "चंडीगढ़",
    "Ludhiana": "लुधियाना",
    "Patna": "पटना",

    # -- bare unit words, for "Quantity in sheets" and the like ------------- #
    "sheet": "शीट",
    "sheets": "शीट",
    "kg": "किलो",
    "box": "डिब्बा",
    "boxes": "डिब्बे",
    "piece": "पीस",
    "pieces": "पीस",
    "roll": "रोल",
    "rolls": "रोल",

    # -- sentences with values in them -------------------------------------- #
    # Translated before the values go in, so the dictionary holds a whole
    # readable sentence instead of fragments to be glued back together.
    "Hi 👋\n\nI can help you get a better price on **{product}** by combining "
    "your order with other buyers in your city.\n\nIt takes a minute — then you "
    "can close this page and we'll message you when the group price improves.":
        "नमस्ते 👋\n\nमैं आपके ऑर्डर को आपके शहर के दूसरे खरीदारों के साथ जोड़कर "
        "**{product}** पर बेहतर कीमत दिलाने में मदद कर सकता हूँ।\n\nएक मिनट लगेगा — "
        "फिर आप यह पेज बंद कर सकते हैं, ग्रुप की कीमत सुधरते ही हम आपको मैसेज कर देंगे।",
    "Sure — {product} 👍\n\n": "ठीक है — {product} 👍\n\n",
    "Quantity in {unit}": "मात्रा ({unit} में)",
    "{qty} kg of": "{qty} किलो",
    "Got it — {counter} {spec}.": "समझ गया — {counter} {spec}।",
    "Got it — {what}.": "समझ गया — {what}।",
    "Added **{picked}** 👍\n\nAnything else with it?":
        "**{picked}** जोड़ दिया 👍\n\nइसके साथ और कुछ?",
    "Now the {product}": "अब {product} की बात",
    "Just the few things a supplier will ask, so we can pool you with other "
    "buyers who need exactly the same thing.":
        "बस वही कुछ बातें जो सप्लायर पूछेगा, ताकि हम आपको उन खरीदारों के साथ जोड़ सकें "
        "जिन्हें बिल्कुल यही चाहिए।",
    "Saved 👍 **{yours}** of {product} — you're the first buyer in this one, so "
    "we'll pool other buyers' orders into it.":
        "सेव हो गया 👍 **{yours}** {product} — इसमें आप पहले खरीदार हैं, तो हम दूसरे "
        "खरीदारों के ऑर्डर इसी में जोड़ते जाएँगे।",
    "Even better — your **{yours}** joins buyers already asking for the same "
    "thing. That group is now at **{pooled}**.":
        "और भी अच्छा — आपके **{yours}** उन खरीदारों के साथ जुड़ गए जो यही माँग रहे थे। "
        "वह ग्रुप अब **{pooled}** पर है।",
    "You're the first buyer in a new **{group}** group 🚀\n\nYour {yours} is now "
    "the starting quantity.":
        "आप नए **{group}** ग्रुप के पहले खरीदार हैं 🚀\n\nआपकी {yours} अब शुरुआती "
        "मात्रा है।",
    "As more buyers with matching requirements join, we'll take the pooled "
    "quantity to suppliers and get you a group price.":
        "जैसे-जैसे मिलती-जुलती ज़रूरत वाले और खरीदार जुड़ेंगे, हम कुल मात्रा लेकर "
        "सप्लायर के पास जाएँगे और आपको ग्रुप कीमत दिलाएँगे।",
    "As more buyers with matching requirements join, the price drops for everyone.":
        "जैसे-जैसे मिलती-जुलती ज़रूरत वाले और खरीदार जुड़ेंगे, सबके लिए कीमत घटती जाएगी।",
    "Good news 🎉\n\nYour {yours} requirement can be combined with other buyers. "
    "There are now approximately **{pooled}** in this buying group.":
        "अच्छी ख़बर 🎉\n\nआपकी {yours} की ज़रूरत दूसरे खरीदारों के साथ जोड़ी जा सकती है। "
        "इस ग्रुप में अब लगभग **{pooled}** हैं।",
    "There's another opportunity 👇 We're only **{gap}** away from the next "
    "price level.":
        "एक और मौका है 👇 अगली कीमत तक पहुँचने में सिर्फ़ **{gap}** की कमी है।",
    "Know someone planning to buy {product}? Invite them to this group. If their "
    "requirement joins, the total quantity increases and **your price can also "
    "become lower.**":
        "किसी को {product} खरीदना है? उन्हें इस ग्रुप में बुलाइए। उनकी ज़रूरत जुड़ने पर "
        "कुल मात्रा बढ़ेगी और **आपकी कीमत भी कम हो सकती है।**",
    "Each of these gets its own buying group too, so we can ask a supplier to "
    "quote them for the whole pool. A few quick questions on each and you're done.":
        "इनमें से हर एक का अपना ग्रुप भी बनेगा, ताकि हम सप्लायर से पूरे पूल के लिए रेट "
        "पूछ सकें। हर एक पर कुछ छोटे सवाल और आपका काम पूरा।",
    "We'll ask the supplier to quote these alongside the {product}, so the group "
    "rate applies to them too. Prices come once the quote is in.":
        "हम सप्लायर से {product} के साथ इनका भी रेट पूछेंगे, ताकि ग्रुप वाली कीमत इन पर "
        "भी लागू हो। रेट आते ही कीमत बता देंगे।",

    # -- cards -------------------------------------------------------------- #
    "Your requests": "आपकी रिक्वेस्ट",
    "Also in your request": "आपकी रिक्वेस्ट में यह भी",
    "You're done 👍": "हो गया 👍",
    "You don't need to keep checking this page. We'll message you when:":
        "आपको यह पेज बार-बार देखने की ज़रूरत नहीं। हम आपको तब मैसेज करेंगे जब:",
    "More buyers join your group": "आपके ग्रुप में और खरीदार जुड़ें",
    "Your group reaches a new quantity level": "आपका ग्रुप नई मात्रा तक पहुँचे",
    "Your price drops": "आपकी कीमत घटे",
    "The final purchase opportunity becomes available": "खरीदने का आख़िरी मौका आए",
    "Want a better price sooner? Share your group with someone who may also be "
    "interested.":
        "और जल्दी बेहतर कीमत चाहिए? अपने ग्रुप को किसी ऐसे व्यक्ति के साथ साझा करें "
        "जिसे इसकी ज़रूरत हो।",
    "We're pooling demand for this product now. As soon as we have enough "
    "quantity we'll get a supplier quote and message you the price.":
        "हम इस प्रोडक्ट की माँग अभी इकट्ठा कर रहे हैं। पर्याप्त मात्रा होते ही हम "
        "सप्लायर से रेट लेकर आपको कीमत बता देंगे।",
}

#: code -> table. English needs none: it is the source.
_TABLES: dict[str, dict[str, str]] = {"hi": HINDI}

#: Measurements and quantities are generated ("18 mm", "8 x 4 ft", "120
#: sheets"), so they can never be dictionary keys. The number is already
#: universal; only the unit word needs saying in Hindi. Longest first, so
#: "sheets" is not matched as "sheet" with a stray "s" left behind.
_UNITS: dict[str, tuple[tuple[str, str], ...]] = {
    "hi": (
        (r"inches", "इंच"), (r"inch", "इंच"),
        (r"sheets", "शीट"), (r"sheet", "शीट"),
        (r"boxes", "डिब्बे"), (r"box", "डिब्बा"),
        (r"pieces", "पीस"), (r"piece", "पीस"),
        (r"rolls", "रोल"), (r"roll", "रोल"),
        (r"units", "नग"), (r"unit", "नग"),
        (r"metres", "मीटर"), (r"metre", "मीटर"),
        (r"feet", "फ़ुट"), (r"ft", "फ़ुट"),
        (r"mm", "मिमी"), (r"kg", "किलो"), (r"g", "ग्राम"),
    ),
}

#: A measurement and *nothing else*: a number, then one unit word. Deliberately
#: strict. A product description ("1 inch Wire Nails", "BWR 18 mm 8 x 4 ft
#: Plywood") is an identity built from trade words, and half-translating it
#: gives "1 इंच Wire कील" -- harder to read than either language on its own.
#: Those stay whole and English, the way MR, BWR and Century do.
_MEASUREMENT = re.compile(r"^\d[\d\s.,x×*/+-]*\s*[A-Za-z]+$")


def _measurement(text: str, lang: str) -> str | None:
    """"18 mm" -> "18 मिमी", "120 sheets" -> "120 शीट". None if not one."""
    units = _UNITS.get(lang)
    if not units or len(text) > 40 or not _MEASUREMENT.match(text):
        return None
    out = text
    for word, hindi in units:
        out = re.sub(rf"\b{word}\b", hindi, out, flags=re.I)
    return out if out != text else None

#: Keys that are identifiers or numbers, never prose -- left alone when a card
#: is walked. Translating a group code or a URL would break the link.
_NEVER_TRANSLATE = {
    "group_code", "url", "referral_code", "intent_id", "status", "type", "code",
    "unit", "product", "group_label", "whatsapp_url", "share_url",
}


def t(text: Any, lang: str | None) -> Any:
    """Translate one display string. Unknown text falls through unchanged."""
    if not isinstance(text, str) or not text:
        return text
    table = _TABLES.get(lang or DEFAULT)
    if table is None:
        return text
    stripped = text.strip()
    hit = table.get(stripped) or _measurement(stripped, lang or DEFAULT)
    if hit is None:
        return text
    return text.replace(stripped, hit, 1)


def phrase(template: str, lang: str | None, **values: Any) -> str:
    """Translate a sentence *before* its values are put in, so the dictionary
    holds a whole readable sentence rather than fragments to be glued."""
    return t(template, lang).format(**values)


def localise(payload: Any, lang: str | None, _key: str | None = None) -> Any:
    """Walk a reply and translate every displayed string in it.

    Chip *labels* are translated; chip *values* are not, and neither is
    anything in `_NEVER_TRANSLATE` -- those are what the server matches on.
    """
    if not lang or lang == DEFAULT:
        return payload
    if isinstance(payload, str):
        return payload if _key in _NEVER_TRANSLATE else t(payload, lang)
    if isinstance(payload, list):
        return [localise(item, lang, _key) for item in payload]
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            # The value a chip sends back must stay exactly as the server
            # wrote it -- it is an instruction, not a sentence.
            out[key] = value if key == "value" else localise(value, lang, key)
        return out
    return payload
