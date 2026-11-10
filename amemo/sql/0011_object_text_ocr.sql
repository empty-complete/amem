-- Откуда текст страницы в кэше object_text: layer — текстовый слой файла, ocr — распознано tesseract (страница
-- без текстового слоя, с картинкой), image — такой же скан, который нечем было распознать (OCR недоступен),
-- none — текста нет вовсе (только page 0). Строка page 0 с image — «текста нет, но это скан»: когда OCR появляется,
-- objects.extraction строит кэш заново.
ALTER TABLE object_text ADD COLUMN text_source text NOT NULL DEFAULT 'layer'
    CHECK (text_source = ANY (ARRAY['layer', 'ocr', 'image', 'none']));
UPDATE object_text SET text_source = 'none' WHERE page = 0;
ALTER TABLE object_text ADD CONSTRAINT object_text_source_page
    CHECK ((page = 0) = (text_source IN ('none', 'image')) OR (page > 0 AND text_source = 'image'));

-- Сброс кэша: PDF без текстового слоя раньше оставался «без текста» (page 0) навсегда; теперь его страницы
-- распознаются, если установлены языковые данные tesseract, — пусть текст извлечётся заново.
DELETE FROM object_text t USING object_version v, object o
 WHERE t.digest = v.digest AND o.id = v.object_id AND t.page = 0
   AND lower(o.original_name) ~ '\.pdf$';
