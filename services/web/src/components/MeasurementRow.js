import React from 'react';
import { Box, Typography, Paper } from '@mui/material';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';

function MeasurementRow({ measurement, data }) {
  const currentValue = data.length > 0 ? data[data.length - 1].value : null;
  
  // Calculate min and max values for Y axis with some padding
  const values = data.map(d => d.value);
  const maxValue = values.length > 0 ? Math.max(...values) : 0;
  const minValue = values.length > 0 ? Math.min(...values) : 0;
  const range = maxValue - minValue;
  const padding = range * 0.1; // Add 10% padding

  return (
    <Paper sx={{ p: 2, mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center' }}>
        <Box sx={{ width: '200px' }}>
          <Typography variant="h6" component="div">
            {measurement.label}
          </Typography>
          <Typography variant="h4" component="div">
            {currentValue !== null ? `${currentValue.toFixed(1)}${measurement.unit}` : 'N/A'}
          </Typography>
        </Box>
        
        <Box sx={{ flexGrow: 1, height: '200px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <XAxis 
                dataKey="timestamp" 
                domain={['auto', 'auto']}
                tickFormatter={(time) => new Date(time).toLocaleTimeString()}
              />
              <YAxis 
                domain={[minValue - padding, maxValue + padding]}
                tickFormatter={(value) => value.toFixed(1)}
                unit={measurement.unit}
              />
              <Tooltip 
                labelFormatter={(label) => new Date(label).toLocaleTimeString()}
                formatter={(value) => [`${value.toFixed(1)}${measurement.unit}`, measurement.label]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#8884d8"
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </Box>
      </Box>
    </Paper>
  );
}

export default MeasurementRow;