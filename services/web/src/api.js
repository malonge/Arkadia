import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export async function fetchSensorData() {
  try {
    console.log('Fetching from:', `${API_BASE_URL}/api/v1/tph`);
    const response = await axios.get(`${API_BASE_URL}/api/v1/tph`);
    console.log('Response:', response.data);
    const { temperature, pressure, humidity, timestamp } = response.data;
    return { temperature, pressure, humidity };
  } catch (error) {
    console.error('Error fetching sensor data:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return {};
  }
} 