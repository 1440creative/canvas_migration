# Canvas LMS API Field Mapping

## PageMeta

| Field           | Endpoint                                   | JSON Key     | Example Value                                           | Notes                       |
| --------------- | ------------------------------------------ | ------------ | ------------------------------------------------------- | --------------------------- |
| id              | `/api/v1/courses/{id}/pages/{url}`         | `page_id`    | `42`                                                    | Always int                  |
| url             | `/api/v1/courses/{id}/pages` & detail      | `url`        | `"welcome"`                                             | Slug used in Canvas URLs    |
| title           | same                                       | `title`      | `"Welcome to the Course"`                               |                             |
| position        | N/A (calculated in export)                 | N/A          | `1`                                                     | Assigned from sort order    |
| module_item_ids | `/api/v1/courses/{id}/modules/{mid}/items` | `id`         | `[101, 102]`                                            | Back-populated later        |
| published       | page detail                                | `published`  | `true`                                                  | Defaults to True if missing |
| updated_at      | page detail                                | `updated_at` | `"2025-08-01T12:34:56Z"`                                | ISO8601                     |
| html_path       | N/A                                        | N/A          | `"pages/001_welcome/index.html"`                        | Relative export path        |
| source_api_url  | N/A                                        | N/A          | `"https://canvas.test/api/v1/courses/42/pages/welcome"` | Construct from base_url     |

## ModuleItemMeta

| Field      | Endpoint     | JSON Key     | Example Value | Notes                                 |
| ---------- | ------------ | ------------ | ------------- | ------------------------------------- |
| id         | module items | `id`         | `555`         |                                       |
| position   | module items | `position`   | `3`           |                                       |
| type       | module items | `type`       | `"Page"`      | e.g. "Page"                           |
| content_id | module items | `content_id` | `42`          | Links to page_id, assignment_id, etc. |
| title      | module items | `title`      | `"Syllabus"`  |                                       |
| url        | module items | `url`        | `"welcome"`   | Sometimes slug, sometimes full path   |

## ModuleMeta

| Field          | Endpoint                       | JSON Key           | Example Value                                       | Notes     |
| -------------- | ------------------------------ | ------------------ | --------------------------------------------------- | --------- |
| id             | `/api/v1/courses/{id}/modules` | `id`               | `7`                                                 |           |
| name           | same                           | `name`             | `"Week 1"`                                          |           |
| position       | same                           | `position`         | `1`                                                 |           |
| published      | same                           | `published`        | `true`                                              |           |
| items          | items endpoint                 | See ModuleItemMeta | —                                                   |           |
| updated_at     | same                           | `updated_at`       | `"2025-08-01T09:30:00Z"`                            |           |
| source_api_url | N/A                            | N/A                | `"https://canvas.test/api/v1/courses/42/modules/7"` | Construct |

## AssignmentMeta

| Field           | Endpoint                           | JSON Key          | Example Value                                            | Notes           |
| --------------- | ---------------------------------- | ----------------- | -------------------------------------------------------- | --------------- |
| id              | `/api/v1/courses/{id}/assignments` | `id`              | `88`                                                     |                 |
| name            | same                               | `name`            | `"Essay 1"`                                              |                 |
| position        | N/A (calculated)                   | N/A               | `2`                                                      | Sort order      |
| published       | same                               | `published`       | `true`                                                   |                 |
| due_at          | same                               | `due_at`          | `"2025-09-15T23:59:00Z"`                                 | ISO8601 or null |
| points_possible | same                               | `points_possible` | `100.0`                                                  | float or null   |
| html_path       | N/A                                | N/A               | `"assignments/002_essay1/index.html"`                    | Relative        |
| updated_at      | same                               | `updated_at`      | `"2025-08-01T10:00:00Z"`                                 |                 |
| module_item_ids | module items                       | `id`              | `[201, 202]`                                             |                 |
| source_api_url  | N/A                                | N/A               | `"https://canvas.test/api/v1/courses/42/assignments/88"` | Construct       |

## FileMeta

| Field           | Endpoint                     | JSON Key                  | Example Value                                        | Notes                |
| --------------- | ---------------------------- | ------------------------- | ---------------------------------------------------- | -------------------- |
| id              | `/api/v1/courses/{id}/files` | `id`                      | `3001`                                               |                      |
| filename        | same                         | `filename`                | `"syllabus.pdf"`                                     |                      |
| content_type    | same                         | `content-type`            | `"application/pdf"`                                  |                      |
| md5             | same                         | `md5`                     | `"abcd1234..."`                                      |                      |
| sha256          | same                         | `sha256`                  | `"efgh5678..."`                                      |                      |
| folder_path     | same                         | `folder` or via folder_id | `"Course Files/Syllabus"`                            |                      |
| file_path       | N/A                          | N/A                       | `"files/syllabus.pdf"`                               | Relative export path |
| module_item_ids | module items                 | `id`                      | `[301]`                                              |                      |
| source_api_url  | N/A                          | N/A                       | `"https://canvas.test/api/v1/courses/42/files/3001"` | Construct            |

## CourseMeta

| Field          | Endpoint                        | JSON Key         | Example Value                             | Notes      |
| -------------- | ------------------------------- | ---------------- | ----------------------------------------- | ---------- |
| id             | `/api/v1/courses/{id}`          | `id`             | `42`                                      |            |
| name           | same                            | `name`           | `"History 101"`                           |            |
| course_code    | same                            | `course_code`    | `"HIST101"`                               |            |
| workflow_state | same                            | `workflow_state` | `"available"`                             |            |
| settings       | `/api/v1/courses/{id}/settings` | Entire JSON      | `{...}`                                   | store raw  |
| exported_root  | N/A                             | N/A              | `"export/data/42"`                        | Local root |
| source_api_url | N/A                             | N/A              | `"https://canvas.test/api/v1/courses/42"` | Construct  |

## CourseStructure

Holds **lists of all other metas** + `CourseMeta`.
