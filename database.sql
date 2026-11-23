CREATE DATABASE IF NOT EXISTS ai_smart_farming CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ai_smart_farming;

CREATE TABLE IF NOT EXISTS farmers (
  farmer_id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(100) NOT NULL,
  email VARCHAR(150) NOT NULL UNIQUE,
  phone VARCHAR(25),
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('farmer','admin') NOT NULL DEFAULT 'farmer',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS farms (
  farm_id INT AUTO_INCREMENT PRIMARY KEY,
  farmer_id INT NOT NULL,
  farm_name VARCHAR(100) NOT NULL,
  location VARCHAR(180) NOT NULL,
  farm_size DECIMAL(10,2),
  soil_type VARCHAR(80),
  irrigation_method VARCHAR(80),
  water_source VARCHAR(80),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS crops (
  crop_id INT AUTO_INCREMENT PRIMARY KEY,
  farm_id INT NOT NULL,
  crop_name VARCHAR(100) NOT NULL,
  variety VARCHAR(100),
  planting_date DATE,
  expected_harvest DATE,
  growth_stage VARCHAR(80) DEFAULT 'Seedling',
  health_status VARCHAR(80) DEFAULT 'Healthy',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS farm_inputs (
  input_id INT AUTO_INCREMENT PRIMARY KEY,
  farm_id INT NOT NULL,
  crop_id INT NULL,
  input_type VARCHAR(80) NOT NULL,
  product_name VARCHAR(120),
  quantity VARCHAR(80),
  input_date DATE NOT NULL,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE,
  FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS disease_cases (
  case_id INT AUTO_INCREMENT PRIMARY KEY,
  farm_id INT NOT NULL,
  crop_id INT NULL,
  issue_name VARCHAR(150) NOT NULL,
  symptoms TEXT,
  reported_date DATE NOT NULL,
  status ENUM('Reported','Under treatment','Monitoring','Recovered') DEFAULT 'Reported',
  treatment_notes TEXT,
  resolved_date DATE NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE,
  FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
