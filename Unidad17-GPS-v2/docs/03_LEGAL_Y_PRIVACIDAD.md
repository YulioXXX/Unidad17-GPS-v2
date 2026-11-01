# Legal y privacidad

> Este documento es una guía práctica, no asesoría jurídica. Antes de desplegar
> el sistema consulta a un abogado y, si hay personal, a la persona responsable
> de recursos humanos.

## Principio de diseño

El sistema está pensado para **saber dónde está un equipo**, no para vigilar a
una persona. Por eso:

* El agente muestra una ventana con su estado en todo momento.
* En el primer arranque muestra un aviso al usuario del equipo.
* No captura pantalla, teclado, archivos ni conversaciones.
* No se oculta del administrador de tareas ni de las herramientas de soporte.
* No se ejecuta de forma encubierta ni se reinstala solo.

Si tu caso de uso requiere ocultar el agente a la persona que usa el equipo,
**este proyecto no es el adecuado**.

## Qué datos se recogen

| Dato | Para qué | Sensibilidad |
|---|---|---|
| Hostname, IP local, IP pública, MAC | Identificar el equipo en la red | Media |
| SO, procesador, arquitectura, RAM, disco libre | Inventario técnico | Baja |
| Latitud, longitud, ciudad, país, precisión | Ubicación del equipo | **Alta** |
| BSSID y señal de redes Wi-Fi cercanas | Triangulación con Google Geolocation | **Alta** (se envían a Google) |
| Fecha y hora de cada reporte | Historial y estado de conexión | Media |
| Usuario que accede al panel y su IP | Auditoría de accesos | Media |

No se recogen nombres de personas, contenido de archivos, historial de
navegación ni credenciales.

> **Tercero implicado:** si configuras la clave de Google, el agente envía a
> Google los BSSID de las redes cercanas. Ese tratamiento se rige también por
> las condiciones y la política de privacidad de Google. Si no quieres enviar
> esos datos, deja la clave vacía: el agente usará solo GPS de Windows o IP.

## Cuándo es legítimo

En términos generales, el rastreo de ubicación de un equipo es admisible si:

1. **El equipo es propiedad de la organización** (o está bajo su
   responsabilidad) y así consta.
2. **La persona usuaria fue informada por escrito** antes de la instalación, con
   lenguaje claro: qué se recoge, para qué, durante qué horario y cómo ejercer
   sus derechos.
3. **La finalidad es concreta y proporcionada**: localizar equipos perdidos,
   gestionar flotas, inventario, soporte. No sirve para evaluar desempeño ni
   para vigilar fuera de la jornada.
4. **Hay una base jurídica** conforme a la normativa aplicable (consentimiento,
   relación laboral, interés legítimo, obligación legal).
5. **Se aplica minimización**: solo los datos necesarios, durante el tiempo
   necesario.

Especial cuidado con:

* Equipos personales de empleados, familiares o terceros.
* Rastrear fuera del horario laboral o en periodos de descanso.
* Usar la ubicación para sancionar sin un procedimiento previo.
* Compartir el panel o la clave de agente con quien no debe acceder.

## Venezuela: referencias

* **Constitución (1999), artículo 28**: derecho de acceso a la información y
  *habeas data*; las personas pueden conocer y solicitar la actualización,
  rectificación o destrucción de datos que les conciernan.
* **Ley Especial contra los Delitos Informáticos (2001)**: acceso indebido a
  sistemas, revelación de información y otros supuestos.
* **Ley de Infogobierno (2013)**: principios de seguridad y protección de datos
  en el sector público.
* **LOTTT**: la relación laboral no elimina los derechos de privacidad; la
  vigilancia debe ser proporcional y conocida.

No existe en Venezuela una ley integral de protección de datos personales
plenamente vigente como en otros países, pero el *habeas data* constitucional y
la normativa penal sí aplican. Si operas en otro país, revisa el RGPD (UE), la
Ley 1581 (Colombia), la LFPDPPP (México) o la norma local correspondiente.

## Obligaciones prácticas

1. **Aviso por escrito** firmado o aceptado por la persona usuaria (ver modelo).
2. **Registro de equipos**: qué equipo, a quién se asignó, desde cuándo.
3. **Acceso restringido**: una cuenta nominal por administrador, contraseña
   fuerte, equipo del panel protegido.
4. **Retención limitada**: borra el historial antiguo con
   `python mantenimiento.py --dias 90`.
5. **Seguridad**: HTTPS en redes no confiables, firewall, copias de seguridad
   cifradas.
6. **Atención de derechos**: canal para que la persona consulte, rectifique o
   pida el borrado de sus datos.

## Modelo de aviso para el equipo

> **Aviso de geolocalización de equipos**
>
> Este equipo informa periódicamente su ubicación y datos técnicos (nombre del
> equipo, direcciones IP, MAC, sistema operativo y hardware) al panel de control
> de [ORGANIZACIÓN], con la finalidad de [localizar equipos extraviados /
> gestionar la flota / inventario y soporte].
>
> La ubicación se obtiene con el servicio de ubicación de Windows o, si no está
> disponible, de forma aproximada a partir de la dirección IP. El agente se
> ejecuta con una ventana visible.
>
> Responsable: [NOMBRE Y CARGO] · Contacto: [CORREO/TELÉFONO]
> Conservación: [90] días · Derechos: [canal de contacto]

Puedes adaptar el texto y entregarlo junto con el contrato o el manual de
bienvenida. Guarda la constancia de entrega.

## Configuración recomendada para cumplir

* `avisar_al_iniciar: true` en `cliente/config.json` (por defecto).
* `intervalo_segundos`: 300–900. No hace falta más frecuencia para localizar un
  equipo y reduce el volumen de datos.
* `minutos_offline`: 15. Ajusta según el intervalo.
* Borrado programado del historial (Programador de tareas):

```bat
python servidor\mantenimiento.py --dias 90
```

## Qué no hacer

* Instalarlo en equipos de personas que no saben que están siendo localizadas.
* Ocultar la ventana con `--noconsole` o mover el `.exe` a carpetas del sistema.
* Usar la ubicación para acoso, control de pareja o vigilancia de menores sin
  autorización legal.
* Vender o ceder los datos a terceros sin base legal.

## Lista de verificación antes de desplegar

- [ ] Los equipos son de la organización o están autorizados.
- [ ] Existe un aviso escrito entregado y registrado.
- [ ] La finalidad está definida y es proporcionada.
- [ ] El horario de recogida está acordado (si aplica).
- [ ] El panel tiene contraseña propia y acceso limitado.
- [ ] Hay un plazo de conservación y un procedimiento de borrado.
- [ ] Se probó el agente con el aviso visible.
- [ ] Se consultó a un abogado si hay dudas.
