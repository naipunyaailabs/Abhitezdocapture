# Docapture API Documentation

Welcome to the **Docapture API** documentation. Our API provides a set of powerful document processing and AI-driven analysis tools, including summarization, RFP generation, quotation comparison, and deep contextual extraction.

## Base URL
The API is currently hosted at:
`http://localhost:5000`

---

## Authentication

The Docapture API uses JWT (JSON Web Token) for authentication. Most endpoints require an Authorization header.

### Header Format
```http
Authorization: Bearer <your_jwt_token>
```

---

## Error Responses

The API uses standard HTTP status codes:
- `200 OK`: Request succeeded.
- `201 Created`: Resource successfully created.
- `400 Bad Request`: Validation error or invalid input.
- `401 Unauthorized`: Authentication missing or invalid.
- `403 Forbidden`: Email not verified or insufficient permissions.
- `404 Not Found`: Resource not found.
- `500 Internal Server Error`: An unexpected error occurred on the server.

Standard JSON Error Format:
```json
{
  "detail": "Error message description"
}
```

---

## Auth Endpoints

### 1. Register User
**POST** `/auth/register`

Register a new account. A verification email will be sent in the background.

**Request Body:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "strongpassword123",
  "agreedToTerms": true
}
```

### 2. Login
**POST** `/auth/login`

Obtain a JWT token for session management.

**Request Body:**
```json
{
  "email": "john@example.com",
  "password": "strongpassword123"
}
```

**Response:**
```json
{
  "token": "eyJhbG...",
  "user": {
    "userId": "...",
    "email": "john@example.com",
    "name": "John Doe",
    "emailVerified": true
  }
}
```

### 3. Verify Email
**GET** `/auth/verify?token=<verification_token>`

Verifies the user's email address using the token sent to their inbox.

### 4. Get Profile
**GET** `/auth/profile` (Auth Required)

Returns the current authenticated user's profile information.

---

## AI Service Endpoints (Auth Required)

### 1. Document Summarization
**POST** `/summarize`

Generates an AI summary of an uploaded document.

**Form Data:**
- `document`: File (PDF, DOCX, TXT, Images)
- `prompt`: (Optional) Focus area for the summary.
- `length`: `short`, `medium`, or `detailed`.

**Response:**
```json
{
  "success": true,
  "data": {
    "result": {
      "summary": "AI generated summary in HTML/Markdown format"
    }
  }
}
```

### 2. Quotation Comparison
**POST** `/compare-quotations`

Compares multiple vendor quotations side-by-side.

**Form Data:**
- `documents`: List of Files (Multiple files allowed)
- `criteria`: (Optional) Specific comparison criteria (e.g., "Best pricing and delivery time").

**Response:**
```json
{
  "success": true,
  "data": {
    "result": {
      "comparison": "Detailed markdown comparison",
      "vendorCount": 2,
      "vendors": ["VendorA", "VendorB"]
    }
  }
}
```

### 3. RFP Generation
**POST** `/rfp/create`

Generates a professional RFP structure based on organizational needs.

**Request Body:**
```json
{
  "title": "Cloud Migration RFP",
  "organization": "Docapture Corp",
  "deadline": "2026-12-31",
  "sections": [
    { "title": "Intro", "content": "RFP Introduction" }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "result": { ...RFP structured content... },
    "message": "RFP content generated successfully"
  }
}
```

### 4. Document Extraction (AI Power Tool)
**POST** `/extract`

Performs deep contextual extraction and parses documents into structured JSON.

**Form Data:**
- `document`: File

**Response:**
```json
{
  "success": true,
  "data": {
    "result": {
      "extracted": {
        "title": "...",
        "author": "...",
        "key_values": { ... }
      },
      "textLength": 1200
    }
  }
}
```

### 5. RFP Summarization
**POST** `/summarize-rfp`

Analyzes complex RFP documents to extract key requirements and deadlines.

**Form Data:**
- `document`: File

---

## Management Endpoints (Auth Required)

### 1. List Services
**GET** `/services`

Returns a list of all active AI services registered in the system.

### 2. Current Subscription
**GET** `/subscription/current`

Returns the user's current plan details and usage limits.

### 3. Processing History
**GET** `/history`

Returns the user's historical document processing records.

### 4. Usage Analytics
**GET** `/history/analytics`

Returns summary statistics of document processing over the last 30 days.

---

## Developer Notes

- **File Uploads**: Ensure you use `multipart/form-data` for endpoints that accept documents.
- **Async Processing**: All AI-heavy endpoints are optimized for high-performance inference via Groq's Llama-3 models.
- **Timeouts**: For large documents or complex comparisons, it is recommended to set a client-side timeout of at least 30-60 seconds.
