#include <LiquidCrystal_I2C.h>
#include <Servo.h>

const int buttonPin = 2;
const int servoPin = 9;

// Sensor ultrasónico para medir nivel de comida
const int pinTrig = 11;
const int pinEcho = 12;

// Variables para cálculos del sensor
long duracion;
int distancia;

int buttonState = 0;         // Estado actual del botón
int lastButtonState = HIGH;  // Estado anterior (HIGH porque usamos PULLUP)

LiquidCrystal_I2C lcd(0x27, 16, 2);
Servo servo;

void aplicarEstado(bool activo) {
  if (activo) {
    digitalWrite(LED_BUILTIN, HIGH);
    servo.write(90);
    lcd.setCursor(0, 1);
    lcd.print("TRUE ");
  } else {
    digitalWrite(LED_BUILTIN, LOW);
    servo.write(0);
    lcd.setCursor(0, 1);
    lcd.print("FALSE");
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(LED_BUILTIN, OUTPUT);
  
  // Configurar pines del sensor ultrasónico
  pinMode(pinTrig, OUTPUT);
  pinMode(pinEcho, INPUT);
  
  lcd.init();
  lcd.backlight();

  servo.attach(servoPin);
  servo.write(0); // posición inicial
  lcd.setCursor(0, 0);
  lcd.print("Sistema listo");
}

void loop() {
  // ===== SENSOR ULTRASÓNICO =====
  // Medir nivel de comida en el recipiente
  digitalWrite(pinTrig, LOW);
  delayMicroseconds(2);
  
  digitalWrite(pinTrig, HIGH);
  delayMicroseconds(10);
  digitalWrite(pinTrig, LOW);
  
  duracion = pulseIn(pinEcho, HIGH);
  distancia = duracion * 0.0343 / 2;
  
  Serial.print("Distancia: ");
  Serial.print(distancia);
  Serial.println(" cm");
  
  // ===== PULSADOR Y SERVO =====
  // Leer el estado del botón
  buttonState = digitalRead(buttonPin);

  // Comparar con el estado anterior para detectar CAMBIOS
  if (buttonState != lastButtonState) {
    
    // Si el estado es LOW, significa que se presionó (por el PULLUP)
    if (buttonState == LOW) {
      Serial.println("TRUE");          // Enviar "TRUE" a Python
      aplicarEstado(true);

    } 
    else {
      Serial.println("FALSE");         // Enviar "FALSE" a Python
      aplicarEstado(false);
    }
    
    // Pequeña espera para evitar rebotes (ruido eléctrico)
    delay(50);
  }

  // Procesar comandos entrantes desde Python/Firebase
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "TRUE") {
      aplicarEstado(true);
    } else if (cmd == "FALSE") {
      aplicarEstado(false);
    }
  }

  // Guardar el estado actual como el último estado para la siguiente vuelta
  lastButtonState = buttonState;
}