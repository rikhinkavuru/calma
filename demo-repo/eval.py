from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

X, y = load_iris(return_X_y=True)
X = X[:, :2]  # sepal length/width only -- the harder, noisier pair
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.4, random_state=7)

clf = LogisticRegression(max_iter=500, random_state=7).fit(Xtr, ytr)
acc = accuracy_score(yte, clf.predict(Xte))
print(f"Test accuracy: {acc:.1%}")
