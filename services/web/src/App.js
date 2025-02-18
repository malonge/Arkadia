import React, { useState, useEffect } from 'react';
import { Container, FormControl, InputLabel, Select, MenuItem, Box } from '@mui/material';
import OutlinedInput from '@mui/material/OutlinedInput';
import Chip from '@mui/material/Chip';
import MeasurementRow from './components/MeasurementRow';
import { fetchSensorData } from './api';

const ITEM_HEIGHT = 48;
const ITEM_PADDING_TOP = 8;
const MenuProps = {
  PaperProps: {
    style: {
      maxHeight: ITEM_HEIGHT * 4.5 + ITEM_PADDING_TOP,
      width: 250,
    },
  },
};

const AVAILABLE_MEASUREMENTS = [
  { id: 'temperature', label: 'Temperature', unit: '°C' },
  { id: 'humidity', label: 'Humidity', unit: '%' },
  { id: 'pressure', label: 'Pressure', unit: 'hPa' },
];

function App() {
  const [selectedMeasurements, setSelectedMeasurements] = useState([]);
  const [measurementData, setMeasurementData] = useState({});

  useEffect(() => {
    const fetchData = async () => {
      const data = await fetchSensorData();
      setMeasurementData(prevData => {
        const newData = { ...prevData };
        Object.keys(data).forEach(key => {
          if (!newData[key]) {
            newData[key] = [];
          }
          newData[key] = [...newData[key], { value: data[key], timestamp: new Date() }]
            .slice(-150); // Keep last 5 minutes of data (150 points at 2-second intervals)
        });
        return newData;
      });
    };

    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleMeasurementChange = (event) => {
    const value = event.target.value;
    setSelectedMeasurements(value);
  };

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <FormControl sx={{ m: 1, width: 300 }}>
        <InputLabel>Measurements</InputLabel>
        <Select
          multiple
          value={selectedMeasurements}
          onChange={handleMeasurementChange}
          input={<OutlinedInput label="Measurements" />}
          renderValue={(selected) => (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {selected.map((value) => (
                <Chip 
                  key={value} 
                  label={AVAILABLE_MEASUREMENTS.find(m => m.id === value)?.label} 
                />
              ))}
            </Box>
          )}
          MenuProps={MenuProps}
        >
          {AVAILABLE_MEASUREMENTS.map((measurement) => (
            <MenuItem key={measurement.id} value={measurement.id}>
              {measurement.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Box sx={{ mt: 4 }}>
        {selectedMeasurements.map((measurementId) => {
          const measurement = AVAILABLE_MEASUREMENTS.find(m => m.id === measurementId);
          return (
            <MeasurementRow
              key={measurementId}
              measurement={measurement}
              data={measurementData[measurementId] || []}
            />
          );
        })}
      </Box>
    </Container>
  );
}

export default App; 