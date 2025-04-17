from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, flash, session
from flask_bootstrap import Bootstrap5
from datetime import datetime
import math
import random
import os
import requests
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
bootstrap = Bootstrap5(app)

TOMTOM_API_KEY = os.getenv('TOMTOM_API_KEY')
TOMTOM_BASE_URL = "https://api.tomtom.com/traffic/services/4"

# Mock database
users = {}
bookings = []

# Mock taxi providers
TAXI_PROVIDERS = [
    {"name": "City Cabs", "logo": "city-cabs.png", "base_price": 50, "price_per_km": 12, "price_per_min": 2},
    {"name": "Quick Ride", "logo": "quick-ride.png", "base_price": 40, "price_per_km": 14, "price_per_min": 2.5},
    {"name": "Luxury Taxis", "logo": "luxury-taxis.png", "base_price": 100, "price_per_km": 25, "price_per_min": 5}
]

class BangaloreUberNow:
    def __init__(self):
        self.rates = { 
            'auto': {
                'base': 30, 'per_km': 14, 'per_min': 0.75,
                'min_fare': 50, 'surge_profile': 'low'
            },
            'ubergo': {
                'base': 45, 'per_km': 16, 'per_min': 1.25,
                'min_fare': 80, 'surge_profile': 'medium'
            },
            'ubersedan': {
                'base': 70, 'per_km': 20, 'per_min': 1.75,
                'min_fare': 120, 'surge_profile': 'high'
            },
            'uberxl': {
                'base': 120, 'per_km': 24, 'per_min': 2.25,
                'min_fare': 200, 'surge_profile': 'high'
            }
        }

    def calculate_fare_and_time(self, vehicle_type, start_coords, end_coords):
        """Calculate fare and duration"""
        distance = self._calculate_distance(start_coords, end_coords)
        duration = (distance / 20) * 60  # 20 km/h average speed
        
        rate = self.rates.get(vehicle_type.lower())
        if not rate:
            raise ValueError(f"Unknown vehicle type: {vehicle_type}")
            
        fare = rate['base'] + (distance * rate['per_km']) + (duration * rate['per_min'])
        return fare, duration
    
    def _calculate_distance(self, start_coords, end_coords):
        """
        Calculate the great-circle distance between two points 
        on the Earth's surface using the Haversine formula.
    
        Args:
            start_coords: Tuple of (latitude, longitude) for start point
            end_coords: Tuple of (latitude, longitude) for end point
    
        Returns:
            Distance in kilometers between the points
        """
        # Extract latitude and longitude from the coordinate tuples
        lat1, lon1 = start_coords
        lat2, lon2 = end_coords
    
        # Radius of the Earth in kilometers
        R = 6371.0
    
        # Convert degrees to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
    
        # Differences in coordinates
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
    
        # Haversine formula
        a = (math.sin(dlat / 2)**2 + 
            math.cos(lat1_rad) * math.cos(lat2_rad) * 
            math.sin(dlon / 2)**2)
    
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
        # Calculate the distance
        distance = R * c

        return distance
    
    def _get_surge_multiplier(self):
        """Get a random surge multiplier between 1.0 and 2.0"""
        return round(random.uniform(1.0, 2.0), 1)


def get_user_location():
    if 'user_latitude' in session and 'user_longitude' in session:
        return (session['user_latitude'], session['user_longitude'])
    
    try: 
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="Hopon")
        location = geolocator.geocode(request.remote_addr)
        if location:
            return (location.latitude, location.longitude)
    except:
        pass
    return None

def get_traffic_data(start_lat, start_lon, end_lat, end_lon):
    try:
        flow_url = f"{TOMTOM_BASE_URL}/flowSegmentData/absolute/10/json"
        flow_params = {
            'point': f"{start_lat},{start_lon}",
            'unit': 'KMPH',
            'key': TOMTOM_API_KEY
        }
        flow_response = requests.get(flow_url, params=flow_params)
        flow_response.raise_for_status()
        flow_data = flow_response.json()
        
        route_url = "https://api.tomtom.com/routing/1/calculateRoute/json"
        route_params = {
            'key': TOMTOM_API_KEY,
            'traffic': 'true',
            'travelMode': 'car',
            'routeType': 'fastest',
            'considerTraffic': 'true',
            'vehicleMaxSpeed': 100
        }
        route_response = requests.get(
            f"{route_url}/{start_lat},{start_lon}:{end_lat},{end_lon}",
            params=route_params
        )
        route_response.raise_for_status()
        route_data = route_response.json()
        
        return {
            'current_speed': flow_data['currentSpeed'],
            'free_flow_speed': flow_data['freeFlowSpeed'],
            'congestion_percentage': flow_data['currentTravelTime'] / flow_data['freeFlowTravelTime'],
            'route_summary': route_data['routes'][0]['summary'],
            'route_geometry': route_data['routes'][0]['legs'][0]['points']
        }
    except Exception as e:
        print(f"Error fetching traffic data: {e}")
        return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/set_location', methods=['POST'])
def set_location():
    if request.method == 'POST':
        data = request.get_json()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        session['user_latitude'] = latitude
        session['user_longitude'] = longitude

        return jsonify({'status': 'success'})

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        # Get form data
        pickup = request.form.get('pickup')
        dropoff = request.form.get('dropoff')
        pickup_time = request.form.get('pickup_time')
        passengers = int(request.form.get('passengers', 1))
        vehicle_type = request.form.get('vehicle_type', 'standard')
        dropoff_coords = request.form.get('dropoff_coords', '').split(',')
        
        # Store in session
        session['search_params'] = {
            'pickup': pickup,
            'dropoff': dropoff,
            'pickup_time': pickup_time,
            'passengers': passengers,
            'vehicle_type': vehicle_type
        }

        estimator = BangaloreUberNow()
        
        # Get coordinates (use user's location if available)
        start_coords = (session.get('user_latitude', 12.9716), session.get('user_longitude', 77.5946))  # Default to Bangalore
        end_coords = (float(dropoff_coords[0]), float(dropoff_coords[1])) if dropoff_coords and len(dropoff_coords) == 2 else (12.9716, 77.5946)
        
        # Map your vehicle types to Uber types
        vehicle_mapping = {
            'standard': 'ubergo',
            'premium': 'ubersedan',
            'xl': 'uberxl',
            'luxury': 'ubersedan'
        }

        # Generate mock quotes
        quotes = []
        for provider in TAXI_PROVIDERS:
            uber_vehicle_type = vehicle_mapping.get(vehicle_type, 'ubergo')
            fare, duration = estimator.calculate_fare_and_time(
                uber_vehicle_type,
                start_coords,
                end_coords
            )
            
            # Calculate distance
            distance = estimator._calculate_distance(start_coords, end_coords)
            
            # Calculate price based on provider rates
            price = provider['base_price']
            price += distance * provider['price_per_km']
            price += (duration / 60) * provider['price_per_min']  # Convert duration to hours
            
            # Apply vehicle type multiplier
            if vehicle_type == 'premium':
                price *= 1.5
            elif vehicle_type == 'xl':
                price *= 1.8
            elif vehicle_type == 'luxury':
                price *= 2.5
            
            # Round to 2 decimal places
            price = round(price, 2)
            
            quotes.append({
                'provider': provider['name'],
                'logo': provider['logo'],
                'price': price,
                'eta': f"{int(duration)} min",
                'distance': f"{distance:.1f} km",
                'vehicle_type': vehicle_type.capitalize(),
                'booking_url': url_for('book', provider=provider['name']),
                'surge': estimator._get_surge_multiplier() > 1.0
            })
        
        # Sort by price
        quotes.sort(key=lambda x: x['price'])
        
        return render_template('results.html', quotes=quotes)
    
    return redirect(url_for('home'))

@app.route('/book/<provider>')
def book(provider):
    if 'search_params' not in session:
        flash('Please perform a search first', 'warning')
        return redirect(url_for('home'))
    
    # In a real app, you would actually book with the provider here
    booking = {
        'provider': provider,
        **session['search_params'],
        'booking_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'status': 'Confirmed',
        'id': len(bookings) + 1
    }
    bookings.append(booking)
    
    flash(f'Your booking with {provider} has been confirmed!', 'success')
    return redirect(url_for('booking_confirmation', booking_id=booking['id']))

@app.route('/booking/<int:booking_id>')
def booking_confirmation(booking_id):
    booking = next((b for b in bookings if b['id'] == booking_id), None)
    if not booking:
        flash('Booking not found', 'danger')
        return redirect(url_for('home'))
    return render_template('booking.html', booking=booking)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Very simple authentication - in a real app, use proper hashing
        if username in users and users[username]['password'] == password:
            session['user'] = username
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if username in users:
            flash('Username already taken', 'danger')
        else:
            users[username] = {'email': email, 'password': password}
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)