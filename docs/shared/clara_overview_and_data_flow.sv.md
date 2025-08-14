### Vad är CLARA

CLARA är en klinisk informationsassistent som hjälper vårdpersonal att snabbt och säkert hitta och sammanfatta relevant patientinformation. Den ansluter till journalsystem (EHR) via etablerade standarder (FHIR och SMART‑on‑FHIR) och kan, när det är lämpligt, berika svar med betrodda externa källor. CLARA presenterar korta, flerspråkiga sammanfattningar i ett lättanvänt webbgränssnitt.

### Vad CLARA gör (Funktionalitet)

- **Sammanfattningar av patientkontext**: Hämtar relevanta vitalparametrar, laboratorievärden, läkemedel, allergier, anamnes och journalanteckningar från EHR och sammanfattar dem för snabb överblick.
- **Frågor och svar för kliniker**: Möjliggör frågor på naturligt språk om patientens journal eller kliniska ämnen; svaren innehåller länkar tillbaka till ursprungskällor när de finns tillgängliga.
- **Stöd för dokumentation**: Hjälper till att generera och förfina kliniska anteckningar eller journaltext, för granskning och godkännande av kliniker innan sparande.

### Mål

- **Hastighet och tydlighet**: Minska tiden till rätt information under kliniskt arbete.
- **Säkerhet och transparens**: Ge tydliga, källhänvisade sammanfattningar som hjälper kliniker att verifiera uppgifter.
- **Sömlös integration**: Fungera med befintliga EHR‑system via öppna standarder.
- **Flerspråkigt stöd**: Stödja mångsidiga vårdteam och patientgrupper.

### Dataflöde på hög nivå

1. **Klinikern använder webbappen** för att be om en sammanfattning eller ställa en fråga.
2. **Backenden hämtar endast nödvändig data** från EHR för att besvara frågan (dataminimering).
3. **Valfritt: betrodda webbkällor** kan konsulteras för att berika svaret när det är lämpligt.
4. **AI sammanställer ett kortfattat svar** och returnerar det till klinikern, inklusive länkar tillbaka till källdata när de finns tillgängliga.
5. **Klinikern granskar och avgör** hur informationen ska användas (t.ex. färdigställa en anteckning).

### Viktiga förtydliganden

- **Inte en medicinteknisk produkt**: CLARA tillhandahåller information och textstöd. Den ställer inte diagnoser, behandlar eller fattar kliniska beslut och får inte användas som ersättning för professionellt omdöme.
- **Kliniker i loopen**: Alla resultat är avsedda för granskning och verifiering av kliniker innan de används i vården.

### Integritet, säkerhet och dataresidens

- **EU‑först‑driftsättning**: Vi planerar att driftsätta CLARA med all data lagrad inom EU med lokala Azure‑molntjänster.
- **GDPR‑principer**: Dataminimering, ändamålsbegränsning och lämpliga retention‑policys.
- **Källtransparens**: Svar strävar efter att inkludera länkar tillbaka till EHR‑objekt eller ange när länk saknas.

### Distributionsupplägg (Sammanfattning)

- **Moln**: Lokala Azure‑tjänster i EU‑regioner för applikationsdrift och datalagring.
- **Standardiserad interoperabilitet**: FHIR/SMART‑on‑FHIR‑anslutningar till partners EHR.
- **Observabilitet och kontroller**: Rollbaserad åtkomst, loggning för spårbarhet och övervakning enligt vedertagna vårdpraxis.

### Begränsningar och icke‑mål

- **Ersätter inte kliniskt beslutsfattande**: CLARA tillhandahåller inte slutliga diagnoser eller behandlingsrekommendationer.
- **Ingen långtidslagring utöver policy**: Patientdata behandlas för att stötta kliniker och lagras enligt överenskomna retention‑policys.


