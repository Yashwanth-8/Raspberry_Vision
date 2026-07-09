Nadi Vision: Auto-Scaling Distance-Locked Visual Acuity Guard 

1. Problem Statement 
A standard visual acuity test assumes that the patient stands about 6 meters away from the vision chart, but this is difficult to achieve in most homes where remote testing is usually performed. As a result, many online vision tests may not provide accurate results. Some existing systems estimate the user's distance using the camera, but they do not continuously adjust the optotype size based on changes in distance during the test. Even if the optotype is displayed correctly at the beginning, the user may move closer to the screen, tilt the device, or change position, which can affect the accuracy of the results. Another limitation is that many systems do not include mechanisms to monitor these changes throughout the test. Our project focuses on addressing these issues by continuously estimating the user's distance, dynamically resizing the optotype, and monitoring movement to help maintain consistent testing conditions. 

2. Objectives 

    1. Conduct surveys with patients, vision center staff, and telemedicine providers to gather information on current vision testing practices, understand the challenges of remote vision testing, and collect feedback to improve the proposed system. 
    2. Identify the most suitable target audience and application area, such as rural vision screening, school eye camps, telemedicine consultations, or driver's license vision screening, based on the survey findings and user feedback. 
    3. Improve distance measurement by integrating a Raspberry Pi with a Time-ofFlight (ToF) distance sensor instead of relying only on camera-based distance estimation. 
    4. Run the face detection and distance estimation algorithms directly on the Raspberry Pi so that the system can work independently without requiring a web browser or continuous internet access. 
    5. Validate the visual acuity scoring by comparing the results with standard clinical methods such as the ETDRS (Early Treatment Diabetic Retinopathy Study) chart to evaluate the system's accuracy. 
    6. Integrate the system with telemedicine platforms so that patients with abnormal test results can be referred for further consultation. 
    7. Further improve the movement and cheating detection mechanisms to make remote vision testing more reliable and consistent.