"""
Train sklearn intent classifier from BrightSmile 10,000-row training dataset.
Reads brightsmile_training_10000.xlsx, uses 19 intents directly from column 3,
trains TF-IDF + LogisticRegression pipeline, saves as intent_classifier.pkl.
"""
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import pickle
import os

DATA_PATH = os.path.expanduser("~/Downloads/brightsmile_training_10000.xlsx")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "intent_classifier.pkl")

df = pd.read_excel(DATA_PATH)

# Column 2 = User Input (index 1), Column 3 = Intent (index 2)
# Use iloc-based column positions in case header names vary
cols = df.columns.tolist()
text_col = cols[1]   # Col 2: User Input
intent_col = cols[2] # Col 3: Intent

df = df.dropna(subset=[text_col, intent_col])

X = df[text_col].astype(str)
y = df[intent_col].astype(str).str.strip()

print(f"Dataset loaded: {len(df)} rows")
print(f"Intents ({y.nunique()}): {sorted(y.unique())}")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

model = Pipeline([
    ("tfidf", TfidfVectorizer(ngram_range=(1, 3), max_features=30000, sublinear_tf=True)),
    ("clf",   LogisticRegression(C=5.0, max_iter=2000, class_weight="balanced"))
])

model.fit(X_train, y_train)
print(classification_report(y_test, model.predict(X_test)))

with open(MODEL_PATH, "wb") as f:
    pickle.dump(model, f)

print(f"Intent classifier trained and saved to {MODEL_PATH}")
print(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
