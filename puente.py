import json
import serial, time, firebase_admin
import threading
from datetime import datetime, date
from pathlib import Path
from firebase_admin import credentials
from firebase_admin import db

# Buffer para promediar distancias (últimas 10 lecturas)
buffer_distancias = []
TAMAÑO_BUFFER = 10

# Función para convertir distancia (cm) a porcentaje de comida
def distancia_a_porcentaje(distancia):
    """
    Convierte la distancia del sensor ultrasónico a un porcentaje.
    - A 1 cm: 99%
    - A mayor distancia: porcentaje disminuye
    """
    distancia_minima = 1      # Distancia mínima (recipiente lleno)
    distancia_maxima = 10     # Distancia máxima (recipiente vacío)
    porcentaje_max = 99       # Porcentaje máximo
    
    if distancia <= distancia_minima:
        return porcentaje_max
    elif distancia >= distancia_maxima:
        return 0
    else:
        # Interpolación lineal
        porcentaje = porcentaje_max * (1 - (distancia - distancia_minima) / (distancia_maxima - distancia_minima))
        return max(0, min(100, int(porcentaje)))  # Limitar entre 0 y 100

def agregar_distancia_y_promediar(distancia):
    """
    Agrega una nueva distancia al buffer y devuelve el promedio si hay suficientes datos.
    """
    global buffer_distancias
    
    buffer_distancias.append(distancia)
    
    # Si el buffer está completo, calcular promedio
    if len(buffer_distancias) >= TAMAÑO_BUFFER:
        promedio = sum(buffer_distancias) / TAMAÑO_BUFFER
        buffer_distancias = []  # Limpiar buffer
        return promedio
    else:
        return None  # Aún no hay suficientes datos

# 1. CONFIGURACIÓN DE FIREBASE
base_dir = Path(__file__).resolve().parent
cred = credentials.Certificate(base_dir / "key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://loginfirebase-2b2b8-default-rtdb.firebaseio.com/' 
})

# Referencias en la base de datos
ref = db.reference('Boton')
schedules_ref = db.reference('schedules')
ref_comida = db.reference('NivelComida')

# Cache local de alarmas para resiliencia sin conexión
schedules_cache = {}
cache_lock = threading.Lock()
cache_file = base_dir / "schedules_cache.json"


def guardar_cache_local(data):
    """Persistir las alarmas en disco para usarlas si no hay Internet."""
    try:
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"No se pudo escribir cache local: {e}")


def cargar_cache_local():
    """Lee las alarmas desde disco si existen."""
    try:
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            print(f"Cache de alarmas leido de disco: {len(data)}")
            return data
    except Exception as e:
        print(f"No se pudo leer cache local: {e}")
    return {}


def cargar_alarmas_iniciales():
    """Obtiene alarmas al iniciar y las almacena en cache por si se cae Internet."""
    global schedules_cache
    try:
        data = schedules_ref.get() or {}
        with cache_lock:
            schedules_cache = data
        guardar_cache_local(data)
        print(f"Alarmas iniciales cargadas: {len(data)}")
    except Exception as e:
        print(f"No se pudieron cargar alarmas al iniciar, intentando cache local: {e}")
        data = cargar_cache_local()
        with cache_lock:
            schedules_cache = data
        print(f"Alarmas cargadas desde cache local: {len(data)}")

# 2b. Listener para cambios en Firebase -> reenviar al Arduino
arduino = None  # se asigna más abajo

# 2c. Helper para pulsar el Boton por 3 segundos
def trigger_boton_pulse(source="alarma"):
    try:
        print(f"Activando Boton por {source}")
        ref.set(True)
        arduino.write(b"TRUE\n")
        # TIEMPO QUE EL SERVO ESTA EN TRUE
        time.sleep(6)
        ref.set(False)
        arduino.write(b"FALSE\n")
        print("Boton restablecido a False")
    except Exception as e:
        print(f"Error activando Boton por {source}: {e}")

def on_db_change(event):
    try:
        valor = event.data
        if valor is True:
            arduino.write(b"TRUE\n")
            print("-> Enviado a Arduino: TRUE (desde Firebase)")
        elif valor is False:
            arduino.write(b"FALSE\n")
            print("-> Enviado a Arduino: FALSE (desde Firebase)")
    except Exception as e:
        print(f"Error enviando al Arduino desde Firebase: {e}")


# 2d. Revisor de alarmas en Firebase -> pulsar Boton
triggered_today = set()
last_trigger_date = date.today()

def alarm_watcher():
    global last_trigger_date, schedules_cache
    while True:
        try:
            now = datetime.now()

            # Reinicia disparos al cambiar de día
            if now.date() != last_trigger_date:
                triggered_today.clear()
                last_trigger_date = now.date()

            try:
                schedules_remote = schedules_ref.get()
                if schedules_remote is not None:
                    with cache_lock:
                        schedules_cache = schedules_remote
                    schedules = schedules_remote
                    guardar_cache_local(schedules_remote)
                else:
                    with cache_lock:
                        schedules = dict(schedules_cache)
                    print(f"Firebase no devolvio datos, usando cache: {len(schedules)}")
            except Exception as e:
                with cache_lock:
                    schedules = dict(schedules_cache)
                print(f"Error obteniendo alarmas (usando cache): {e}")
            current_time = now.strftime("%H:%M")

            for schedule_id, schedule in schedules.items():
                scheduled_time = None

                if isinstance(schedule, dict):
                    scheduled_time = schedule.get("time")
                elif isinstance(schedule, str):
                    scheduled_time = schedule

                if not isinstance(scheduled_time, str):
                    continue

                scheduled_time = scheduled_time.strip()
                if not scheduled_time:
                    continue

                if scheduled_time == current_time and schedule_id not in triggered_today:
                    triggered_today.add(schedule_id)
                    threading.Thread(
                        target=trigger_boton_pulse,
                        args=(f"alarma {schedule_id}",),
                        daemon=True,
                    ).start()
                    print(f"Alarma {schedule_id} disparada a las {current_time}")

        except Exception as e:
            print(f"Error revisando alarmas: {e}")

        time.sleep(15)

# 2. CONFIGURACIÓN DEL PUERTO SERIAL
# Asegúrate de que el COM sea el correcto y el Monitor Serial de Arduino esté CERRADO
arduino = serial.Serial('COM7', 9600, timeout=1) 
time.sleep(2) # Espera para el reset del Arduino

# Cargar alarmas al iniciar para tener cache local
cargar_alarmas_iniciales()

# Registrar escucha de cambios en Firebase
ref.listen(on_db_change)

# Lanzar el hilo que revisa alarmas programadas
threading.Thread(target=alarm_watcher, daemon=True).start()

print("Sistema listo. Presiona el botón en el Arduino...")

# 3. BUCLE PRINCIPAL (Leer Arduino -> Escribir Firebase)
while True:
    try:
        # Verificamos si hay datos esperando en el puerto serial
        if arduino.in_waiting > 0:
            # Leemos la línea, decodificamos bytes a string y quitamos espacios/saltos
            lectura = arduino.readline().decode('utf-8').strip()
            
            print(f"Recibido de Arduino: {lectura}")

            # Lógica para actualizar Firebase
            if lectura == "TRUE":
                ref.set(True)  # Sube un booleano real (true)
                print("-> Firebase actualizado a: True")
                
            elif lectura == "FALSE":
                ref.set(False) # Sube un booleano real (false)
                print("-> Firebase actualizado a: False")
            
            # Procesar lecturas del sensor ultrasónico (Distancia: X cm)
            elif lectura.startswith("Distancia:"):
                try:
                    # Extraer el valor numérico de la lectura
                    # Ej: "Distancia: 5 cm" -> 5
                    partes = lectura.split()
                    distancia = float(partes[1])
                    
                    # Agregar al buffer y obtener promedio si está completo
                    promedio = agregar_distancia_y_promediar(distancia)
                    
                    if promedio is not None:
                        # Convertir promedio a porcentaje
                        porcentaje = distancia_a_porcentaje(promedio)
                        
                        # Subir a Firebase
                        ref_comida.set(porcentaje)
                        print(f"-> Distancias: {buffer_distancias + [distancia][-3:]} cm -> Promedio: {promedio:.2f} cm -> Porcentaje: {porcentaje}%")
                        print(f"-> Firebase actualizado a: {porcentaje}%")
                    else:
                        print(f"-> Distancia recibida: {distancia} cm (acumulando para promedio: {len(buffer_distancias)}/{TAMAÑO_BUFFER})")
                except (IndexError, ValueError) as e:
                    print(f"Error al procesar distancia: {e}")

    except KeyboardInterrupt:
        print("\nPrograma terminado por el usuario.")
        arduino.close()
        break
    except Exception as e:
        print(f"Error: {e}")