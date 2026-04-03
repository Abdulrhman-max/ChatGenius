"""
Train sklearn intent classifier from BrightSmile dental QA dataset.
Reads dental_chatbot_qa_final.xlsx, maps categories to intents, trains
TF-IDF + LogisticRegression pipeline, saves as intent_classifier.pkl.
"""
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import pickle
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "dental_chatbot_qa_final.xlsx")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "intent_classifier.pkl")

df = pd.read_excel(DATA_PATH)

intent_map = {
    "Appointment Scheduling":      "book_appointment",
    "Doctor Availability":         "check_availability",
    "Dental Services Info":        "services_info",
    "Pricing & Payment":           "pricing_info",
    "Office Hours & Location":     "office_hours",
    "Oral Hygiene Tips":           "oral_hygiene",
    "Specialist Recommendations":  "specialist_recommendation",
    "Post-Treatment Care":         "post_treatment",
    "Emergency Dental":            "emergency",
    "General Dental Questions":    "general_dental",
}

df["intent"] = df["Category"].map(intent_map)
df = df.dropna(subset=["intent", "Question"])

X = df["Question"].astype(str)
y = df["intent"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

model = Pipeline([
    ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=10000)),
    ("clf",   LogisticRegression(max_iter=1000))
])

model.fit(X_train, y_train)
print(classification_report(y_test, model.predict(X_test)))

with open(MODEL_PATH, "wb") as f:
    pickle.dump(model, f)

print(f"Intent classifier trained and saved to {MODEL_PATH}")
print(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
