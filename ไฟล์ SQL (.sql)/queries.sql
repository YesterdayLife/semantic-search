-- SQLite 3; execute after: python src/build.py
-- Q01 / FR-01: Thai cassava production from FAOSTAT in 2019.
SELECT c.crop_name,p.year_ce,p.area,s.title,e.quantity,e.unit,e.review_status
FROM exchange e JOIN process p ON p.process_id=e.process_id
JOIN crop c ON c.crop_id=p.crop_id
JOIN data_source s ON s.source_id=e.source_id
WHERE c.crop_id='CAS' AND p.year_ce=2019 AND e.source_id='SRC-01';

-- Q02 / FR-02: dry-season rice indicators; moisture basis remains NULL when absent in source.
SELECT p.year_original,p.season,i.metric_code,i.value,i.unit,i.moisture_basis
FROM crop_indicator i JOIN process p ON p.process_id=i.process_id
WHERE p.crop_id='RIC' AND p.source_id='SRC-04' AND p.season='dry' AND p.year_ce=2024
UNION ALL
SELECT p.year_original,p.season,'production',e.quantity,e.unit,NULL
FROM exchange e JOIN process p ON p.process_id=e.process_id
WHERE p.crop_id='RIC' AND p.source_id='SRC-04' AND p.season='dry' AND p.year_ce=2024
ORDER BY metric_code;

-- Q03 / FR-03: all exchanges of one process, with provenance.
SELECT p.process_id,e.direction,f.flow_name,e.quantity,e.unit,s.title,p.source_file,e.source_row
FROM exchange e JOIN process p ON p.process_id=e.process_id
JOIN flow f ON f.flow_id=e.flow_id JOIN data_source s ON s.source_id=e.source_id
WHERE p.process_id='P-SRC-01-CAS-all-2019';

-- Q04 / FR-04: processes lacking measured Input exchanges.
SELECT count(*) AS processes_without_input FROM process p
WHERE NOT EXISTS (SELECT 1 FROM exchange e WHERE e.process_id=p.process_id AND e.direction='Input');

-- Q05 / FR-05: only these processes could support normalization per 1 t output.
WITH product_output AS (
  SELECT process_id, SUM(quantity) AS output_t
  FROM exchange WHERE direction='Output' AND unit='t' AND quantity>0
  GROUP BY process_id
)
SELECT p.process_id, f.flow_name AS input_flow,
       i.quantity / o.output_t AS input_per_t, i.unit AS input_unit
FROM process p JOIN product_output o ON o.process_id=p.process_id
JOIN exchange i ON i.process_id=p.process_id AND i.direction='Input'
JOIN flow f ON f.flow_id=i.flow_id
WHERE o.output_t>0;

-- Q06 / FR-06, BR-01/02/05: wrong source, nonpositive output, and duplicate keys.
SELECT 'missing_source' AS issue,count(*) AS n FROM exchange e
LEFT JOIN data_source s ON s.source_id=e.source_id WHERE s.source_id IS NULL
UNION ALL SELECT 'invalid_output',count(*) FROM exchange
WHERE direction='Output' AND (quantity<=0 OR unit<>'t')
UNION ALL SELECT 'duplicate_exchange',count(*) FROM
(SELECT process_id,flow_id,direction,count(*) k FROM exchange
 GROUP BY process_id,flow_id,direction HAVING k>1);

-- Q07 / DR-01: accepted rows by source; each row keeps source file and row number.
SELECT s.source_id,s.title,count(DISTINCT p.process_id) AS processes,
count(DISTINCT e.exchange_id) AS output_rows,
count(DISTINCT i.indicator_id) AS indicator_rows
FROM data_source s LEFT JOIN process p ON p.source_id=s.source_id
LEFT JOIN exchange e ON e.process_id=p.process_id
LEFT JOIN crop_indicator i ON i.process_id=p.process_id
GROUP BY s.source_id,s.title ORDER BY s.source_id;

-- Q08 / DR-02/05, Thailand relevance: required process fields and location.
SELECT count(*) AS invalid_process FROM process
WHERE crop_id IS NULL OR year_ce NOT BETWEEN 2019 AND 2024
OR year_original='' OR calendar NOT IN ('CE','BE') OR boundary=''
OR (spatial_level='country' AND (area<>'Thailand' OR region_code IS NOT NULL))
OR (spatial_level='region' AND region_code IS NULL);

-- Q09 / DR-03, BR-03: area and yield remain indicators, not material exchanges.
SELECT (SELECT count(*) FROM flow) AS product_flows,
(SELECT count(*) FROM crop_indicator) AS non_flow_indicators;

-- Q10 / DR-07: only validated output exchanges are counted.
SELECT review_status,count(*) AS n FROM exchange GROUP BY review_status;

-- Q11 / BR-04: Buddhist Era to Common Era conversion for OAE.
SELECT count(*) AS invalid_year_conversion FROM process
WHERE calendar='BE' AND CAST(year_original AS INTEGER)-543<>year_ce;

-- Q12 / DR-06, BR-07: moisture basis availability in dry-season rice indicators.
SELECT count(*) AS dry_rice_indicators,
SUM(CASE WHEN i.moisture_basis IS NOT NULL THEN 1 ELSE 0 END) AS with_moisture_basis
FROM crop_indicator i JOIN process p ON p.process_id=i.process_id
WHERE p.crop_id='RIC' AND p.season='dry';

-- Q13 / DR-01: source metadata completeness, without inventing publication years.
SELECT count(*) AS sources,
SUM(CASE WHEN publication_year IS NOT NULL THEN 1 ELSE 0 END) AS with_publication_year,
SUM(CASE WHEN url<>'' AND agency<>'' THEN 1 ELSE 0 END) AS with_url_agency
FROM data_source;

-- Q14 / DR-04, BR-01: exchange joins and physical source-file references.
SELECT count(*) AS output_rows,
SUM(CASE WHEN p.process_id IS NOT NULL AND f.flow_id IS NOT NULL
 AND s.source_id IS NOT NULL AND sf.file_path IS NOT NULL
 AND sf.source_id=e.source_id THEN 1 ELSE 0 END) AS fully_linked
FROM exchange e LEFT JOIN process p ON p.process_id=e.process_id
LEFT JOIN flow f ON f.flow_id=e.flow_id
LEFT JOIN data_source s ON s.source_id=e.source_id
LEFT JOIN source_file sf ON sf.file_path=p.source_file;

-- Q15 / FR-07: 2024 maize by region, with reporting province counts.
SELECT p.year_ce,p.area AS region,e.quantity AS production_t,
       ra.reporting_provinces,ra.provinces_in_region,
       CASE WHEN ra.reporting_provinces<ra.provinces_in_region
         THEN 'reporting provinces fewer than all provinces in region'
         ELSE 'all provinces represented' END AS coverage_note,
       ra.national_reconciled,s.title
FROM process p JOIN exchange e ON e.process_id=p.process_id
JOIN regional_aggregate ra ON ra.process_id=p.process_id
JOIN data_source s ON s.source_id=p.source_id
WHERE p.crop_id='MAI' AND p.year_ce=2024 AND p.spatial_level='region'
ORDER BY p.area;

-- Q16 / BR-08, FR-07: regional output sum versus same-source national output.
SELECT p.source_id,p.crop_id,p.year_ce,
       SUM(e.quantity) AS region_sum_t,
       (SELECT en.quantity FROM exchange en JOIN process pn ON pn.process_id=en.process_id
        WHERE pn.source_id=p.source_id AND pn.crop_id=p.crop_id
          AND pn.year_ce=p.year_ce AND pn.spatial_level='country') AS country_t,
       SUM(e.quantity)-(SELECT en.quantity FROM exchange en JOIN process pn ON pn.process_id=en.process_id
        WHERE pn.source_id=p.source_id AND pn.crop_id=p.crop_id
          AND pn.year_ce=p.year_ce AND pn.spatial_level='country') AS difference_t
FROM process p JOIN exchange e ON e.process_id=p.process_id
WHERE p.spatial_level='region' GROUP BY p.source_id,p.crop_id,p.year_ce
ORDER BY p.source_id,p.year_ce;

-- Q17 / DR-08, BR-08: map and region-process integrity.
SELECT (SELECT count(*) FROM region) AS defined_regions,
       (SELECT count(*) FROM province_region_map) AS mapped_provinces,
       (SELECT count(DISTINCT region_code) FROM process WHERE spatial_level='region') AS represented_regions,
       (SELECT count(*) FROM process p LEFT JOIN region r ON r.region_code=p.region_code
        WHERE p.spatial_level='region' AND r.region_code IS NULL) AS invalid_region_process,
       (SELECT count(*) FROM regional_contribution rc
        JOIN process p ON p.process_id=rc.process_id
        JOIN province_region_map m ON m.province=rc.province
        WHERE p.region_code<>m.region_code) AS mismatched_contribution_region;

-- Q18 / BR-03: derived regional yields match production / area.
SELECT count(*) AS regional_yield_rows,
       MAX(ABS(y.value-e.quantity*1000/a.value)) AS maximum_difference_kg_per_rai
FROM crop_indicator y JOIN process p ON p.process_id=y.process_id
JOIN exchange e ON e.process_id=p.process_id AND e.direction='Output'
JOIN crop_indicator a ON a.process_id=p.process_id
 AND a.metric_code=CASE y.metric_code WHEN 'yield_planted' THEN 'area_planted' ELSE 'area_harvested' END
WHERE p.spatial_level='region' AND y.metric_code IN ('yield_planted','yield_harvested');

-- Q19 / DR-08: every province observation points to a region process and source row.
SELECT count(*) AS source_rows,
       count(DISTINCT process_id) AS regional_processes,
       SUM(CASE WHEN source_row>0 AND source_file<>'' THEN 1 ELSE 0 END) AS traceable_rows
FROM regional_contribution;
