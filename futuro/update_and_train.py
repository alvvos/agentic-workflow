from sincronizar_datos import actualizar_datos_csv
from ml.prediccion import MotorPredictivo

def pipeline_actualizacion():
    df = actualizar_datos_csv()
    motor = MotorPredictivo()
    motor.entrenar(df)

if __name__ == "__main__":
    pipeline_actualizacion()