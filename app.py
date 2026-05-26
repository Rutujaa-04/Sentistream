# ==============================
# 1. IMPORTS
# ==============================
import pickle
import re
import os
import json
import time
import datetime
import streamlit as st
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from lime.lime_text import LimeTextExplainer
from scipy.sparse import hstack

# ==============================
# 2. PAGE CONFIG
# ==============================
st.set_page_config(
    page_title="Human-in-the-Loop Resume Screening",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for premium look
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        color: white;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: rgba(255,255,255,0.05);
        backdrop-filter: blur(10px);
        border-right: 1px solid rgba(255,255,255,0.1);
    }

    /* Card / metric styling */
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.07);
        border-radius: 12px;
        padding: 1rem;
        border: 1px solid rgba(255,255,255,0.1);
        transition: all 0.3s ease;
    }
    [data-testid="stMetric"]:hover {
        background: rgba(255,255,255,0.12);
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }

    /* Primary button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea, #764ba2);
        border: none;
        border-radius: 10px;
        color: white;
        font-weight: 600;
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(102,126,234,0.4);
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(102,126,234,0.6);
    }

    /* Success / error / warning boxes */
    .stSuccess { border-radius: 12px; }
    .stError   { border-radius: 12px; }
    .stWarning { border-radius: 12px; }

    /* Section headers */
    h2, h3 { color: #a78bfa; }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: rgba(255,255,255,0.7);
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea, #764ba2) !important;
        color: white !important;
    }

    /* Code-like word badges */
    .word-badge {
        display: inline-block;
        background: rgba(102,126,234,0.2);
        border: 1px solid rgba(102,126,234,0.4);
        border-radius: 6px;
        padding: 2px 8px;
        font-family: monospace;
        font-size: 0.9em;
        margin: 2px;
        color: #a78bfa;
    }

    /* Confidence bar */
    .conf-bar-container {
        background: rgba(255,255,255,0.1);
        border-radius: 20px;
        height: 12px;
        overflow: hidden;
        margin: 6px 0;
    }

    /* Activity log entries */
    .log-entry {
        background: rgba(255,255,255,0.05);
        border-left: 3px solid #764ba2;
        border-radius: 0 8px 8px 0;
        padding: 8px 12px;
        margin: 4px 0;
        font-size: 0.85em;
    }
</style>
""", unsafe_allow_html=True)

# ==============================
# 3. LOAD SAVED MODEL FILES
# ==============================
@st.cache_resource
def load_models():
    base_dir = os.path.dirname(__file__)
    # Prefer files/ artifacts (improved model), fall back to root
    def _load(filename):
        improved = os.path.join(base_dir, "files", filename)
        root     = os.path.join(base_dir, filename)
        path     = improved if os.path.exists(improved) else root
        with open(path, "rb") as f:
            return pickle.load(f)

    model          = _load("model.pkl")
    vectorizer     = _load("vectorizer.pkl")
    char_vectorizer = _load("char_vectorizer.pkl")
    le             = _load("label_encoder.pkl")
    return model, vectorizer, char_vectorizer, le

model, vectorizer, char_vectorizer, le = load_models()

# ==============================
# 5. GROUP MAP  (raw category → semantic group)
#    Covers all 54 categories in the expanded dataset
# ==============================
GROUP_MAP = {
    # ── Tech / Engineering ──────────────────────────────────────────────
    'information technology'      : 'tech',
    'information-technology'      : 'tech',
    'engineering'                 : 'tech',
    'electrical engineering'      : 'tech',
    'mechanical engineer'         : 'tech',
    'java developer'              : 'tech',
    'python developer'            : 'tech',
    'react developer'             : 'tech',
    'dotnet developer'            : 'tech',
    'sap developer'               : 'tech',
    'data science'                : 'tech',
    'etl developer'               : 'tech',
    'sql developer'               : 'tech',
    'devops'                      : 'tech',
    'database'                    : 'tech',
    'testing'                     : 'tech',
    'network security engineer'   : 'tech',
    'blockchain'                  : 'tech',
    'web designing'               : 'tech',

    # ── Finance ─────────────────────────────────────────────────────────
    'finance'                     : 'finance',
    'accountant'                  : 'finance',
    'banking'                     : 'finance',

    # ── Management / Business ───────────────────────────────────────────
    'management'                  : 'management',
    'consultant'                  : 'management',
    'operations manager'          : 'management',
    'business analyst'            : 'management',
    'pmo'                         : 'management',
    'business-development'        : 'management',
    'business development'        : 'management',

    # ── HR ──────────────────────────────────────────────────────────────
    'human resources'             : 'hr',
    'hr'                          : 'hr',

    # ── Sales / Marketing ───────────────────────────────────────────────
    'sales'                       : 'sales',
    'public relations'            : 'sales',
    'public-relations'            : 'sales',

    # ── Legal ───────────────────────────────────────────────────────────
    'advocate'                    : 'legal',

    # ── Healthcare ──────────────────────────────────────────────────────
    'healthcare'                  : 'healthcare',

    # ── Creative / Design ───────────────────────────────────────────────
    'arts'                        : 'creative',
    'digital media'               : 'creative',
    'digital-media'               : 'creative',
    'apparel'                     : 'creative',
    'designing'                   : 'creative',
    'designer'                    : 'creative',
    'architecture'                : 'creative',

    # ── Education ───────────────────────────────────────────────────────
    'education'                   : 'education',
    'teacher'                     : 'education',

    # ── Hospitality / Food ──────────────────────────────────────────────
    'chef'                        : 'hospitality',
    'food and beverages'          : 'hospitality',

    # ── Aviation ────────────────────────────────────────────────────────
    'aviation'                    : 'aviation',

    # ── Construction ────────────────────────────────────────────────────
    'construction'                : 'construction',
    'building and construction'   : 'construction',
    'civil engineer'              : 'construction',

    # ── Fitness ─────────────────────────────────────────────────────────
    'fitness'                     : 'fitness',
    'health and fitness'          : 'fitness',

    # ── Agriculture ─────────────────────────────────────────────────────
    'agriculture'                 : 'agriculture',

    # ── Automobile ──────────────────────────────────────────────────────
    'automobile'                  : 'automobile',

    # ── BPO / Support ───────────────────────────────────────────────────
    'bpo'                         : 'bpo',
}

# ── Helper: apply group map ─────────────────────────────────────────────
def apply_group_map(raw_category: str) -> str:
    """Map a raw dataset category label to its semantic group."""
    return GROUP_MAP.get(raw_category.lower().strip(), raw_category.lower().strip())

# ──────────────────────────────────────────────────────────────────────────
# 6. KEYWORD BOOST  (all 16 semantic groups)
# ──────────────────────────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    'tech'        : ['python', 'java', 'react', 'node', 'sql', 'machine learning',
                     'cloud', 'docker', 'aws', 'kubernetes', 'api', 'devops',
                     'javascript', 'typescript', 'c++', 'golang', 'rust', 'spark',
                     'tensorflow', 'pytorch', 'fastapi', 'microservices', 'ci/cd',
                     'git', 'linux', 'bash', 'rest', 'graphql', 'blockchain',
                     'data science', 'etl', 'testing', 'selenium', 'qa', 'network',
                     'cybersecurity', 'sap', 'dotnet', '.net'],
    'finance'     : ['accounting', 'audit', 'financial', 'tax', 'balance sheet',
                     'budgeting', 'cfa', 'cpa', 'investment', 'ledger', 'tally',
                     'gst', 'ifrs', 'gaap', 'reconciliation', 'forecasting',
                     'banking', 'credit', 'loan', 'treasury', 'equity'],
    'management'  : ['leadership', 'strategy', 'stakeholder', 'kpi', 'agile',
                     'project management', 'pmp', 'hiring', 'scrum', 'roadmap',
                     'p&l', 'cross-functional', 'operations', 'business analyst',
                     'consulting', 'pmo', 'change management', 'okr'],
    'hr'          : ['recruitment', 'talent acquisition', 'onboarding', 'payroll',
                     'hris', 'performance review', 'employee relations', 'hrms',
                     'compensation', 'benefits', 'workforce', 'hr policy',
                     'learning and development', 'l&d', 'culture'],
    'sales'       : ['revenue', 'pipeline', 'crm', 'leads', 'quota', 'b2b',
                     'negotiation', 'client acquisition', 'salesforce', 'target',
                     'cold calling', 'upsell', 'cross-sell', 'business development',
                     'account management', 'pr', 'media', 'branding campaign'],
    'legal'       : ['litigation', 'contract', 'legal drafting', 'court', 'advocate',
                     'arbitration', 'compliance', 'ipc', 'crpc', 'legal research',
                     'intellectual property', 'ip', 'patent', 'corporate law'],
    'healthcare'  : ['clinical', 'patient', 'diagnosis', 'nursing', 'ehr',
                     'hipaa', 'pharmacy', 'medical', 'hospital', 'doctor',
                     'mbbs', 'surgery', 'therapy', 'physiotherapy', 'oncology'],
    'creative'    : ['design', 'photoshop', 'illustrator', 'figma', 'branding',
                     'typography', 'ux', 'ui', 'adobe', 'visual', 'animation',
                     'motion graphics', 'sketch', 'indesign', 'canva',
                     'fashion', 'textile', 'apparel', 'architectural design', 'cad'],
    'education'   : ['curriculum', 'teaching', 'pedagogy', 'classroom',
                     'lesson plan', 'students', 'assessment', 'tutoring',
                     'faculty', 'professor', 'e-learning', 'cbse', 'icse',
                     'academic', 'research', 'dissertation'],
    'hospitality' : ['culinary', 'kitchen', 'chef', 'menu', 'catering',
                     'food safety', 'restaurant', 'cuisine', 'pastry',
                     'hospitality', 'banquet', 'beverage', 'fssai', 'haccp'],
    'aviation'    : ['pilot', 'aircraft', 'atc', 'faa', 'flight', 'cockpit',
                     'navigation', 'airline', 'maintenance', 'dgca', 'cpl',
                     'atpl', 'airworthiness', 'avionics', 'cabin crew'],
    'construction': ['civil', 'blueprint', 'contractor', 'osha', 'structural',
                     'construction', 'project site', 'estimation', 'autocad',
                     'revit', 'bar bending', 'rcc', 'quantity surveying',
                     'building', 'architecture drawing'],
    'fitness'     : ['trainer', 'workout', 'nutrition', 'gym', 'personal training',
                     'wellness', 'coaching', 'exercise', 'crossfit', 'yoga',
                     'physiotherapy', 'dietitian', 'sports', 'rehabilitation'],
    'agriculture' : ['farming', 'crop', 'soil', 'irrigation', 'harvest',
                     'agronomy', 'livestock', 'pesticide', 'horticulture',
                     'organic', 'seeds', 'fertilizer', 'agri', 'dairy'],
    'automobile'  : ['mechanic', 'engine', 'diagnostic', 'automotive', 'repair',
                     'transmission', 'vehicle', 'servicing', 'ev', 'electric vehicle',
                     'obd', 'chassis', 'workshop', 'automobile workshop'],
    'bpo'         : ['call center', 'customer support', 'escalation', 'helpdesk',
                     'ticketing', 'sla', 'chat support', 'inbound', 'outbound',
                     'voice process', 'non-voice', 'bpo', 'kpo', 'ites'],
}

def keyword_boost(text, category):
    keywords = CATEGORY_KEYWORDS.get(category, [])
    matches  = sum(1 for kw in keywords if kw in text.lower())
    return min(matches * 0.02, 0.15)

# ==============================
# 6. TEXT CLEANING
# ==============================
def clean_resume(text):
    text = re.sub(r'<.*?>', ' ', text)
    text = re.sub(r'http\S+|www\S+', ' ', text)
    text = re.sub(r'\d+', ' ', text)
    text = re.sub(r'[^a-zA-Z ]', ' ', text)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def remove_stopwords(text):
    words = text.split()
    return " ".join(w for w in words if w not in ENGLISH_STOP_WORDS)

def advanced_clean(text):
    text  = clean_resume(text)
    text  = remove_stopwords(text)
    words = [w for w in text.split() if 3 <= len(w) <= 15]
    return " ".join(words)

# ==============================
# 7. ML PREDICTION
# ==============================
def predict_resume(text):
    cleaned    = advanced_clean(text)
    word_vec   = vectorizer.transform([cleaned])
    char_vec   = char_vectorizer.transform([cleaned])
    vec        = hstack([word_vec, char_vec])
    pred       = model.predict(vec)[0]
    probs      = model.predict_proba(vec)
    confidence = float(probs.max())
    category   = le.inverse_transform([pred])[0]
    confidence = min(confidence + keyword_boost(cleaned, category), 1.0)

    # Top-3 predictions with probabilities
    top3_idx   = probs[0].argsort()[-3:][::-1]
    top3       = [(le.inverse_transform([i])[0], float(probs[0][i])) for i in top3_idx]

    return category, confidence, top3

# ==============================
# 8. LIME EXPLAINABILITY
# ==============================
class_names = list(le.classes_)
explainer   = LimeTextExplainer(class_names=class_names)

def predict_proba_lime(texts):
    cleaned  = [advanced_clean(t) for t in texts]
    word_vec = vectorizer.transform(cleaned)
    char_vec = char_vectorizer.transform(cleaned)
    return model.predict_proba(hstack([word_vec, char_vec]))

def explain_prediction(text, num_features=12):
    exp = explainer.explain_instance(text, predict_proba_lime, num_features=num_features)
    return [(w, s) for w, s in exp.as_list() if abs(s) > 0.01]

# ==============================
# 9. RESERVED FOR FUTURE ENHANCEMENTS
# ==============================

# ==============================
# 10. SESSION STATE INIT
# ==============================
if "feedback_data" not in st.session_state:
    st.session_state.feedback_data = []
if "activity_log" not in st.session_state:
    st.session_state.activity_log = []

# ==============================
# 11. MAIN APP
# ==============================
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    st.divider()
    st.markdown("## 📊 Session Summary")

    total     = len(st.session_state.feedback_data)
    selected  = sum(1 for r in st.session_state.feedback_data if "Selected" in r.get("final_decision", ""))
    rejected  = sum(1 for r in st.session_state.feedback_data if "Rejected" in r.get("final_decision", ""))
    overrides = sum(1 for r in st.session_state.feedback_data if r.get("human_override") != "Accept AI Decision")

    col1, col2 = st.columns(2)
    col1.metric("Analyzed", total)
    col2.metric("Selected", selected)
    col1.metric("Rejected", rejected)
    col2.metric("Overrides", overrides)

    if total > 0:
        accept_rate = round((selected / total) * 100, 1)
        st.progress(selected / total if total else 0, text=f"Accept rate: {accept_rate}%")

    st.divider()
    st.markdown("## 📝 Activity Log")
    if st.session_state.activity_log:
        for entry in reversed(st.session_state.activity_log[-5:]):
            st.markdown(f'<div class="log-entry">{entry}</div>', unsafe_allow_html=True)
    else:
        st.caption("No activity yet")

    st.divider()
    # Export data
    if st.session_state.feedback_data:
        export_data = json.dumps(st.session_state.feedback_data, indent=2)
        st.download_button(
            label="📥 Export Session Data (JSON)",
            data=export_data,
            file_name=f"screening_session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

# ==============================
# 12. HEADER
# ==============================
st.markdown("""
<div style="text-align:center; padding: 1.5rem 0 0.5rem 0;">
    <h1 style="font-size: 2.4rem; font-weight: 700;
               background: linear-gradient(135deg, #667eea, #a78bfa, #f472b6);
               -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
        📄 Human-in-the-Loop Resume Screening
    </h1>
    <p style="color: rgba(255,255,255,0.6); font-size: 1rem; margin-top: -0.5rem;">
        AI-powered · Explainable · Human-controlled
    </p>
</div>
""", unsafe_allow_html=True)

# Status bar
col_a, col_b = st.columns(2)
col_a.success("🤖 ML Model: **Ensemble (SVM + LogReg + RF)**")
col_b.success("🔍 LIME: **Explainability Active**")

st.divider()

# ==============================
# 13. TABS
# ==============================
tab1 = st.tabs([
    "🔍 Screen Resume",
])[0]

# ────────────────────────────────────────────
# TAB 1 — MAIN SCREENING
# ────────────────────────────────────────────
with tab1:
    col1, col2 = st.columns([2, 1])

    with col1:
        resume = st.text_area(
            "📝 Paste Resume Text",
            height=280,
            placeholder="Paste the full resume content here...",
            key="tab1_resume"
        )

    with col2:
        target_role = st.selectbox("🎯 Target Role", sorted(list(le.classes_)), key="tab1_role")
        st.caption("**Confidence thresholds:**")
        st.caption("< 40% → Auto-Reject/Review")
        st.caption("40–70% → Needs Human Review")
        st.caption("> 70% → AI decides")

        lime_features = st.slider("LIME Features", 5, 20, 12, key="lime_feat")

    if st.button("🔍 Analyze Resume", type="primary", use_container_width=True, key="btn_analyze"):

        if not resume.strip():
            st.warning("⚠️ Please paste resume text first.")
        else:
            # ── ML Prediction ──────────────────────────────────────
            with st.spinner("🧠 Running ML model..."):
                category, confidence, top3 = predict_resume(resume)

            st.subheader("🤖 ML Model Results")
            m1, m2, m3 = st.columns(3)
            m1.metric("Predicted Role", category.upper())
            m2.metric("Confidence",     f"{confidence:.0%}")
            m3.metric("Target Role",    target_role.upper())

            # Confidence visual bar
            conf_color = "#22c55e" if confidence >= 0.7 else ("#f59e0b" if confidence >= 0.4 else "#ef4444")
            st.markdown(f"""
            <div class="conf-bar-container">
                <div style="width:{min(confidence*100,100):.1f}%; height:100%;
                            background:linear-gradient(90deg,{conf_color}88,{conf_color});
                            border-radius:20px; transition:width 0.8s ease;"></div>
            </div>
            """, unsafe_allow_html=True)

            # Top-3 alternative predictions
            with st.expander("📊 Top-3 Predictions"):
                for rank, (cat, prob) in enumerate(top3, 1):
                    st.write(f"**#{rank}** `{cat}` — {prob:.1%}")

            # Decision
            if confidence < 0.4:
                decision = "❌ Low Confidence — Reject or Review"
                st.error(f"**Decision:** {decision}")
            elif confidence < 0.7:
                decision = "⚠️ Medium Confidence — Needs Human Review"
                st.warning(f"**Decision:** {decision}")
            elif category == target_role:
                decision = "✅ Strong Match — Selected"
                st.success(f"**Decision:** {decision}")
            else:
                decision = f"❌ Not Matching Role (predicted: {category})"
                st.error(f"**Decision:** {decision}")

            # ── LIME Explanation ────────────────────────────────────
            st.subheader("🧠 LIME Explainability")
            with st.spinner("Computing explanation..."):
                explanation = explain_prediction(resume, num_features=lime_features)

            if explanation:
                pos = sorted([(w, s) for w, s in explanation if s > 0], key=lambda x: -x[1])
                neg = sorted([(w, s) for w, s in explanation if s < 0], key=lambda x: x[1])
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**✅ Supporting words:**")
                    for w, s in pos[:8]:
                        st.markdown(f'<span class="word-badge">+{s:.3f}</span> `{w}`', unsafe_allow_html=True)
                with c2:
                    st.markdown("**❌ Opposing words:**")
                    for w, s in neg[:8]:
                        st.markdown(f'<span class="word-badge">{s:.3f}</span> `{w}`', unsafe_allow_html=True)

            # ── Human Override ──────────────────────────────────────
            st.divider()
            st.subheader("👤 Human Override")

            hr_col1, hr_col2 = st.columns([2, 1])
            with hr_col1:
                human_decision = st.selectbox(
                    "Override AI Decision",
                    ["Accept AI Decision", "Force Select", "Force Reject"],
                    key="tab1_override"
                )
                override_reason = st.text_input(
                    "Reason for override (optional)",
                    placeholder="e.g., Domain expertise evident despite low keyword match",
                    key="tab1_reason"
                )
            with hr_col2:
                reviewer = st.text_input("Reviewer Name", placeholder="Your name", key="tab1_reviewer")
                priority = st.select_slider("Priority", ["Low", "Medium", "High"], value="Medium", key="tab1_priority")

            if human_decision == "Accept AI Decision":
                final_decision = decision
            elif human_decision == "Force Select":
                final_decision = "Selected ✅"
            else:
                final_decision = "Rejected ❌"

            st.subheader("✅ Final Decision")
            if "Selected" in final_decision:
                st.success(f"**{final_decision}**")
            elif "Rejected" in final_decision:
                st.error(f"**{final_decision}**")
            else:
                st.warning(f"**{final_decision}**")

            # ── Log entry ───────────────────────────────────────────
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            record = {
                "timestamp"      : timestamp,
                "resume_snippet" : resume[:200],
                "ai_prediction"  : category,
                "confidence"     : round(confidence, 3),
                "ai_decision"    : decision,
                "human_override" : human_decision,
                "override_reason": override_reason,
                "reviewer"       : reviewer,
                "priority"       : priority,
                "target_role"    : target_role,
                "final_decision" : final_decision,
            }
            st.session_state.feedback_data.append(record)
            st.session_state.activity_log.append(
                f"{timestamp} | {target_role} | {final_decision[:20]}"
            )

            # ── Session Stats ────────────────────────────────────────
            st.divider()
            st.subheader("📊 Session Stats")
            total2     = len(st.session_state.feedback_data)
            selected2  = sum(1 for r in st.session_state.feedback_data if "Selected" in r["final_decision"])
            overrides2 = sum(1 for r in st.session_state.feedback_data if r["human_override"] != "Accept AI Decision")
            avg_conf   = sum(r["confidence"] for r in st.session_state.feedback_data) / total2

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Total Analyzed",  total2)
            s2.metric("Selected",        selected2)
            s3.metric("Human Overrides", overrides2)
            s4.metric("Avg Confidence",  f"{avg_conf:.0%}")

