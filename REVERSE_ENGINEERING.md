# DogLog App - Reverse Engineering Findings

## App Identity
- **Package**: `com.mobikode.dog`
- **APK**: 12.8MB (extracted from XAPK)
- **Architecture**: Android (Java/Kotlin), Firebase backend

## Firebase Project
- **Project ID**: `doglog-18366`
- **Realtime Database URL**: `https://doglog-18366.firebaseio.com`
- **Cloud Functions**: `https://us-central1-doglog-18366.cloudfunctions.net/`
- **Storage Bucket**: `doglog-18366.appspot.com`
- **Google API Key**: `AIzaSyCBNSh63pQeV7qB1igqF_QK56xTXuAS-zE`
- **Google App ID**: `1:727208592142:android:f02e60b1229ffa28`
- **GCM Sender ID**: `727208592142`
- **OAuth Client ID**: `727208592142-3bvib9btsl71ddapj9b6pgn9ppvd8ov9.apps.googleusercontent.com`

## Authentication
- Firebase Auth with Google Sign-In (request code 123) and Facebook Sign-In (request code 124)
- Auth tokens passed as `Authorization` header to Cloud Functions (Bearer token)

## API Endpoints

### Cloud Functions (Retrofit)
Only one REST endpoint found:
- **POST** `removeAccount` — deletes user account
  - Headers: `Content-Type: application/json`, `Accept: application/json`
  - Auth: `Authorization: <bearer_token>`
  - Body: `HashMap<String, Object>`

### Firebase Realtime Database (primary data access)
All other data access is via Firebase Realtime Database SDK directly.

## Database Schema

### Top-Level Nodes
| Node | Description |
|------|-------------|
| `packs` | Pack (group) containers |
| `pets` | Pet data (legacy?) |
| `users` | User accounts |
| `allUsers` | Global user directory |
| `externalInvites` | External invitation codes |
| `reminderData` | Reminder storage |
| `logsfirebase` | Firebase logging |
| `CSVReports` | Exported CSV reports |
| `content` | Static reference data |

### `/packs/{packId}/`
```
name: string
mod: string (owner userId)
dateCreated: long
lastEdit: long
members/
  {userId}: object
    premium: boolean
pets/
  {petId}: object
    name: string
    free: boolean
    profile/
      PersonalInfo: PetInfo object
      PetCareProviders: PetCareProviders object
events/
  {eventId}: Event object
customActions/
  {actionId}: CustomAction object
medicineFavorites/
  {medicineId}: object
```

### `/users/{userId}/`
```
name: string
email: string
uid: string
premium: boolean
packs: [packId, ...]
pets: [petId, ...]
invites/
  {inviteId}: Invite object
purchases: object
```

### `/content/`
```
breedValues: object (breed database)
breedVersion: int
foodValues: object (food/nutrition database)
foodVersion: int
vaccineValues: object
medicineValuesV2: object
quantityNames: object
stoolQualityNames: object
premiumScreen: object
premiumPackMaxPetsAmount: int
partnersValues: object
partnersVersion: int
```

## Data Models

### Event (type integers 0-17)
| Type | Name | Category |
|------|------|----------|
| 0 | FOOD | DIET |
| 1 | TREAT | DIET |
| 2 | WALK | OUTDOORS |
| 3 | PEE | OUTDOORS |
| 4 | POOP | OUTDOORS |
| 5 | TEETH_BRUSHING | CARE |
| 6 | GROOMING | CARE |
| 7 | TRAINING | CARE |
| 8 | MEDICINE | MEDICAL |
| 9 | SPARE | CARE |
| 10 | EVENT | CUSTOM |
| 11 | PHOTO | CARE |
| 12 | WEIGHT | MEDICAL |
| 13 | TEMPERATURE | MEDICAL |
| 14 | WATER | DIET |
| 15 | SLEEP | CARE |
| 16 | VACCINE | MEDICAL |
| 17 | BLOOD_GLUCOSE | MEDICAL |

### Event Fields
```json
{
  "eventId": "string",
  "user": "userId",
  "userName": "string",
  "petId": "string",
  "pet": "petName",
  "date": "long (epoch ms)",
  "type": "int (0-17, see above)",
  "typeV2": "int (nullable)",
  "typeV3": "int (nullable)",
  "comment": "string",
  "visible": "boolean (default true)",
  "photoevent": "boolean",
  "customActionId": "string",
  "customActionOneTimeTitle": "string",
  "quantity": "double",
  "quantityUnit": "string",
  "startTime": "long",
  "endTime": "long",
  "weightKg": "double",
  "weightPound": "double",
  "weightMeasure": "string (Kilograms|Pounds)",
  "temperatureCelsius": "double",
  "temperatureFahrenheit": "double",
  "temperatureMeasure": "string (Celsius|Fahrenheit)",
  "stoolQualityUnit": "string",
  "medicineUnit": "string",
  "vaccine": "string",
  "vaccineExpirationDate": "long",
  "glucose": "double",
  "glucoseUnit": "string (mg/dL|mmol/L)",
  "comments": [{"date": "long", ...}],
  "likes": [{"date": "long", ...}]
}
```

### Pet
```json
{
  "petId": "string",
  "name": "string",
  "dateCreated": "long",
  "free": "boolean"
}
```

### PetInfo (profile)
```json
{
  "birthday": "long (epoch seconds)",
  "breed": "string",
  "country": "string",
  "weightInt": "int",
  "weightFrac": "int",
  "chip": "string",
  "license": "string",
  "foodBrand": "string",
  "foodAmount": "int",
  "foodAmountFraction": "string",
  "foodUnit": "string (CM³|OZ|KG|CUPS)",
  "zipCode": "string"
}
```

### Pack
```json
{
  "root": "userId (creator)",
  "dateCreated": "long",
  "name": "string",
  "mod": "string (moderator userId)"
}
```

### UserData
```json
{
  "name": "string",
  "email": "string",
  "uid": "string",
  "premium": "boolean",
  "packs": ["packId", ...],
  "pets": ["petId", ...]
}
```

## Units
- **Weight**: Kilograms, Pounds
- **Temperature**: Celsius, Fahrenheit
- **Blood Glucose**: mg/dL, mmol/L
- **Food**: CM³, OZ, KG, CUPS

## Other Constants
- `MAX_PETS_COUNT_IN_FREE_PACK`: 3
- `MAX_INPUT_FIELD_LENGTH`: 15
- `MAX_INPUT_PROFILE_NAME_LENGTH`: 100
- Monthly product: `doglog.monthly.android`
- Yearly product: `doglog.yearly.android`

## Network Config
- OkHttp 4.9.0
- Retrofit with Gson converter
- 30-second timeouts (connect, read, write)

## Key Source Files
- Retrofit client: `jadx-output/sources/u5/C1814a.java`
- API interface: `jadx-output/sources/v5/c.java`
- Firebase DB wrappers: `jadx-output/sources/w5/` (C1853a, C1858f, G, k, r, s, v, w, z, l)
- Constants: `jadx-output/sources/com/mobikode/dog/constants/`
- Models: `jadx-output/sources/com/mobikode/dog/domain/model/`
