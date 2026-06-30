# GridSearchCV (default scoring = estimator.score) computes accuracy MANY times inside sklearn — one per
# fold×param — via ClassifierMixin.score, which our shim hooks at the class level (so these ARE captured,
# tagged user_site=False because sklearn's own code makes the call). The headline is the single accuracy
# the repo's OWN code computes on the held-out test set. The binder must collapse to the latter.
from sklearn.datasets import load_iris
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score

X, y = load_iris(return_X_y=True)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0)
gs = GridSearchCV(SVC(), {"C": [0.1, 1, 10]}, cv=3)   # default scoring → estimator.score per fold
gs.fit(Xtr, ytr)
acc = accuracy_score(yte, gs.predict(Xte))            # the repo's own (user-site) headline
print("test accuracy:", round(acc, 4))
