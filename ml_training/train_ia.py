"""CU-11: entrena el clasificador de daño de paquete (MobileNetV2 transfer learning).

Transfer learning real: MobileNetV2 pre-entrenado en ImageNet (congelado) como
extractor + cabeza densa de 3 clases. Datos: sinteticos (synth_images) por no
tener fotos reales; para produccion dropear fotos reales y reentrenar.
Correr: python -m ml_training.train_ia
"""
import json

import numpy as np

from app.ml_models.features import (
    CLASES_IA,
    IA_CLASSES_PATH,
    IA_IMG_SIZE,
    IA_MODEL_PATH,
)
from ml_training.synth_images import gen_dataset


def build_model():
    import tensorflow as tf

    base = tf.keras.applications.MobileNetV2(
        input_shape=(IA_IMG_SIZE, IA_IMG_SIZE, 3),
        include_top=False,
        weights="imagenet",  # descarga ~14MB la 1a vez
    )
    base.trainable = False  # transfer learning: base congelada

    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input((IA_IMG_SIZE, IA_IMG_SIZE, 3)),
            tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1),  # = preprocess MobileNetV2
            base,
            tf.keras.layers.GlobalAveragePooling2D(),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(len(CLASES_IA), activation="softmax"),
        ]
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def main():
    print("Generando dataset sintetico...")
    X, y = gen_dataset(n_por_clase=240, size=IA_IMG_SIZE, seed=42)
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    cut = int(len(X) * 0.8)
    X_tr, X_te = X[:cut].astype("float32"), X[cut:].astype("float32")
    y_tr, y_te = y[:cut], y[cut:]

    print(f"train={len(X_tr)} test={len(X_te)}  | construyendo MobileNetV2...")
    model = build_model()
    model.fit(X_tr, y_tr, validation_data=(X_te, y_te), epochs=6, batch_size=32, verbose=2)

    loss, acc = model.evaluate(X_te, y_te, verbose=0)
    print(f"=== test accuracy = {acc:.3f} ===")

    model.save(IA_MODEL_PATH)
    IA_CLASSES_PATH.write_text(json.dumps(CLASES_IA, ensure_ascii=False), encoding="utf-8")
    print(f"Modelo guardado en {IA_MODEL_PATH}")


if __name__ == "__main__":
    main()
