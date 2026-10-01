Start:
streamlit run Dashboard.py

Sponsoren-Deadline-Mailing:
- Aktuelle Sponsorenliste im XLSX-Format hochladen und das Blatt `Deals` wählen.
- München ist für den 17.–19.11.2026 voreingestellt. Onboarding: 18.–31.08.; Unterlagen: 15.10.; Präsentation: 29.10.; Teilnehmerliste: 03.11.; Gesprächswünsche: 10.11.
- Für ein Folgeevent Stadt und Eventstart einstellen. Eventende und Deadlines werden automatisch verschoben. Unter „Deadlines und Eventdetails“ lassen sich abweichende Termine sowie Link, Veranstaltungsort und Check-in einstellen. Die automatischen Abstände sind 91/78 Tage für das Onboarding und 33/19/14/7 Tage vor Eventstart für die übrigen Deadlines.
- Spalten werden anhand ihrer Überschriften erkannt, auch wenn sie verschoben werden. `Posting erhalten` ersetzt den Check in `Posting gepostet` nicht. Onboarding und Gesprächswünsche werden ebenfalls ausgewertet. Vorträge gelten für Gold und Platin.
- Das aktuelle Layout von `00_MUC26_Master_SPO_Infos.xlsx` wird unterstützt: `Sponsor`, `Target Account Liste erhalten` und die verschobenen Statusspalten für Posting, Präsentation und Gesprächswünsche. `Sponsorinfos erhalten` und `Zusatzinfos` ersetzen keine Aufgaben-Checks.
- Eindeutig zugeordnete Checks aus `Bookletinformationen` und `Vortragsinformationen` ergänzen den Status aus `Deals`. Vollständige Vortragsdetails einschließlich Sprecherfoto zählen als vorliegende Vortragsinformationen; einzelne Angaben oder der Druckstatus reichen dafür nicht aus. Ein eingetragenes Vortragsdatum muss zum gewählten Event passen.
- Mehrere E-Mail-Adressen in einer Kontaktzelle sind erlaubt, getrennt durch Zeilenumbruch, Semikolon oder Komma. Alle Adressen werden in der Vorschau angezeigt und bei Entwürfen und Versand berücksichtigt.
- Nach Änderungen an Datei oder Einstellungen neu generieren und die Vorschau prüfen. Geänderte Einstellungen verwerfen die vorherige Vorschau. Die Generierung benötigt keine Mail-Zugangsdaten; Entwürfe und Versand benötigen ein eingerichtetes Postfach.
